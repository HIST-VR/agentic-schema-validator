from collections import defaultdict
from decimal import Decimal

import pytest
from pydantic import ValidationError

from extraction_engine.engine import extract, requires_provider_call
from extraction_engine.errors import ExtractionError
from extraction_engine.schemas.invoice import Invoice
from extraction_engine.tracing import field_paths, scrub


class ScriptedClient:
    """One create() call that replays the hook sequence Instructor runs internally."""

    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = outcomes
        self.handlers: dict[str, list] = defaultdict(list)
        self.calls: list[dict] = []

    def on(self, name: str, fn) -> None:
        self.handlers[name].append(fn)

    def _emit(self, name: str, *args: object, **kwargs: object) -> None:
        for handler in self.handlers.get(name, []):
            handler(*args, **kwargs)

    def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        messages = list(kwargs.get("messages") or [])
        max_retries = int(kwargs.get("max_retries", 0))
        attempts = max_retries + 1
        last_error: Exception | None = None
        for index in range(attempts):
            meta = {"attempt_number": index + 1, "max_attempts": attempts}
            self._emit(
                "completion:kwargs",
                **{**kwargs, "messages": messages, "_instructor_meta": meta},
            )
            outcome = self.outcomes[min(index, len(self.outcomes) - 1)]
            if isinstance(outcome, Exception):
                last_error = outcome
                self._emit("completion:response", {"rejected": True})
                self._emit("parse:error", outcome)
                is_last = index + 1 >= attempts
                self._emit(
                    "completion:error",
                    outcome,
                    attempt_number=index + 1,
                    max_attempts=attempts,
                    is_last_attempt=is_last,
                )
                if is_last:
                    raise outcome
                messages = [
                    *messages,
                    {
                        "role": "user",
                        "content": f"The following ValidationError was raised:\n{outcome}\nFix the arguments.",
                    },
                ]
                continue
            self._emit("completion:response", {"parsed": True})
            return outcome
        raise last_error or RuntimeError("script ended without a result")


def _invoice(**overrides: object) -> Invoice:
    payload: dict[str, object] = {
        "invoice_number": "INV-1",
        "vendor_name": "Northwind",
        "currency": "USD",
        "line_items": [
            {"description": "Sensor", "quantity": 4, "unit_price": "125.00"},
            {"description": "Brackets", "quantity": 10, "unit_price": "18.50"},
            {"description": "Freight", "quantity": 1, "unit_price": "64.00"},
        ],
        "total_amount": "749.00",
    }
    payload.update(overrides)
    return Invoice.model_validate(payload)


def _capture_total_error() -> ValidationError:
    with pytest.raises(ValidationError) as caught:
        _invoice(total_amount="540.00")
    return caught.value


def test_retry_records_the_validation_error_and_the_feedback() -> None:
    error = _capture_total_error()
    client = ScriptedClient([error, _invoice()])
    result = extract(
        source_text="messy invoice",
        schema_key="invoice",
        provider_key="google",
        model_name="gemini-3.5-flash",
        max_retries=3,
        client=client,
    )
    assert result.ok
    assert result.attempts == 2
    assert Decimal(str(result.data["total_amount"])) == Decimal("749.00")
    assert any(event.kind == "validation_error" and "540.00" in event.detail for event in result.events)
    assert any(
        event.kind == "validation_error" and "total_amount" in event.fields for event in result.events
    )
    assert any(event.kind == "retry_feedback" and "540.00" in event.detail for event in result.events)
    assert result.checks


def test_exhausted_validation_is_a_clean_failure() -> None:
    error = _capture_total_error()
    client = ScriptedClient([error, error])
    result = extract(
        source_text="messy invoice",
        schema_key="invoice",
        provider_key="google",
        model_name="gemini-3.5-flash",
        max_retries=1,
        client=client,
    )
    assert not result.ok
    assert result.data is None
    assert result.attempts == 2
    assert result.error_message
    assert sum(event.kind == "validation_error" for event in result.events) == 2


def test_google_omits_temperature_and_openai_sends_zero() -> None:
    client = ScriptedClient([_invoice()])
    extract(
        source_text="invoice",
        schema_key="invoice",
        provider_key="google",
        model_name="gemini-3.5-flash",
        client=client,
    )
    assert "temperature" not in client.calls[0]

    openai_client = ScriptedClient([_invoice()])
    extract(
        source_text="invoice",
        schema_key="invoice",
        provider_key="openai",
        model_name="gpt-4.1-mini",
        client=openai_client,
    )
    assert openai_client.calls[0]["temperature"] == 0


def test_secrets_are_scrubbed_from_the_trace() -> None:
    class Boom:
        def on(self, *_args: object, **_kwargs: object) -> None:
            return None

        def create(self, **_kwargs: object) -> object:
            raise RuntimeError("provider rejected key sk-secret-value")

    result = extract(
        source_text="invoice",
        schema_key="invoice",
        provider_key="google",
        model_name="gemini-3.5-flash",
        api_key="sk-secret-value",
        client=Boom(),
    )
    blob = (result.error_message or "") + "".join(event.detail for event in result.events)
    assert "sk-secret-value" not in blob
    assert "***" in blob


def test_empty_text_and_missing_key_do_not_call_a_provider() -> None:
    empty = extract(
        source_text="   ",
        schema_key="invoice",
        provider_key="google",
        model_name="gemini-3.5-flash",
        environ={},
    )
    assert not empty.ok
    assert "empty" in (empty.error_message or "").lower()

    missing = extract(
        source_text="an invoice",
        schema_key="invoice",
        provider_key="google",
        model_name="gemini-3.5-flash",
        environ={},
    )
    assert not missing.ok
    assert "GEMINI_API_KEY" in (missing.error_message or "")


def test_unknown_schema_is_an_extraction_error() -> None:
    result = extract(
        source_text="hello",
        schema_key="contract",
        provider_key="google",
        model_name="gemini-3.5-flash",
        environ={},
    )
    assert not result.ok
    assert "Unknown schema" in (result.error_message or "")


def test_field_paths_names_the_rejected_total() -> None:
    assert field_paths(_capture_total_error()) == ("total_amount",)


def test_requires_provider_call_skips_local_failures() -> None:
    assert not requires_provider_call(
        source_text="   ",
        model_name="gemini-3.5-flash",
        max_retries=3,
        api_key="present",
    )
    assert not requires_provider_call(
        source_text="an invoice",
        model_name="gemini-3.5-flash",
        max_retries=3,
        api_key="  ",
    )
    assert not requires_provider_call(
        source_text="x" * 100_001,
        model_name="gemini-3.5-flash",
        max_retries=3,
        api_key="present",
    )
    assert requires_provider_call(
        source_text="an invoice",
        model_name="gemini-3.5-flash",
        max_retries=3,
        api_key="present",
    )


def test_scrub_redacts_authorization_lines() -> None:
    cleaned = scrub("Authorization: Bearer sk-live\napi_key=abc", "sk-live")
    assert "sk-live" not in cleaned
    assert "abc" not in cleaned
