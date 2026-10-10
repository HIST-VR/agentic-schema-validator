"""Run one structured extraction and keep the retry trace."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
import time
import traceback
from typing import Any

from pydantic import BaseModel, ValidationError

from extraction_engine.errors import ExtractionError
from extraction_engine.prompts import user_prompt
from extraction_engine.providers import Provider, build_client, get_provider, resolve_api_key
from extraction_engine.schemas.registry import SchemaSpec, get_schema
from extraction_engine.tracing import (
    MAX_TRACEBACK_CHARS,
    TraceCollector,
    TraceEvent,
    attach_hooks,
    clip,
    field_paths,
    format_exception,
    record_failed_attempts,
    scrub,
    scrub_events,
)

MAX_SOURCE_CHARS = 100_000
DEFAULT_MAX_RETRIES = 3


@dataclass
class ExtractionResult:
    ok: bool
    schema_key: str
    schema_label: str
    provider_key: str
    provider_label: str
    model_name: str
    attempts: int
    latency_ms: int
    data: dict[str, Any] | None
    checks: list[str]
    events: list[TraceEvent]
    error_message: str | None


def extract(
    *,
    source_text: str,
    schema_key: str,
    provider_key: str,
    model_name: str,
    api_key: str = "",
    max_retries: int = DEFAULT_MAX_RETRIES,
    client: Any | None = None,
    environ: Mapping[str, str] | None = None,
) -> ExtractionResult:
    """Extract one document. Pass `client` in tests to avoid a network call."""
    started = time.perf_counter()
    events: list[TraceEvent] = []
    secret = ""
    spec: SchemaSpec | None = None
    provider: Provider | None = None
    resolved_model = (model_name or "").strip()
    try:
        spec = get_schema(schema_key)
        try:
            provider = get_provider(provider_key)
        except KeyError as exc:
            raise ExtractionError(str(exc)) from exc
        _check_request(source_text, resolved_model, max_retries)
        if client is None:
            secret = resolve_api_key(provider, api_key, environ)
            client = build_client(provider, resolved_model, secret)
        elif api_key.strip():
            secret = api_key.strip()

        temperature = "0" if provider.supports_temperature else "provider default"
        events.append(
            TraceEvent(
                kind="start",
                title="Run started",
                detail=(
                    f"Agent: {spec.label}\n"
                    f"Schema: {spec.model.__name__}\n"
                    f"Provider: {provider.label}\n"
                    f"Model: {resolved_model}\n"
                    f"max_retries: {max_retries}\n"
                    f"temperature: {temperature}"
                ),
            )
        )
        collector = TraceCollector(events)
        attach_hooks(client, collector)
        parsed = call_model(
            client,
            _create_payload(spec, provider, resolved_model, source_text, max_retries),
        )
        if not isinstance(parsed, BaseModel):
            raise ExtractionError(
                f"The provider returned {type(parsed).__name__}, which is not a validated schema object."
            )
        data = parsed.model_dump(mode="json")
        checks = list(getattr(parsed, "acceptance_summary", lambda: [])())
        attempts = _attempt_count(events, minimum=1)
        events.append(
            TraceEvent(
                kind="success",
                title="Validation passed",
                detail=f"Accepted {spec.model.__name__} after {attempts} attempt(s).",
                attempt=attempts,
            )
        )
        return _finish(
            ok=True,
            spec=spec,
            provider=provider,
            model_name=resolved_model,
            attempts=attempts,
            started=started,
            data=data,
            checks=checks,
            events=events,
            error_message=None,
            secret=secret,
        )
    except ExtractionError as exc:
        return _failure(
            spec=spec,
            provider=provider,
            schema_key=schema_key,
            provider_key=provider_key,
            model_name=resolved_model,
            started=started,
            events=events,
            error_message=str(exc),
            secret=secret,
        )
    except _retry_exception_types() as exc:
        record_failed_attempts(events, exc)
        reported = getattr(exc, "n_attempts", None)
        attempts = _attempt_count(events, minimum=reported if isinstance(reported, int) else 0)
        if not any(event.kind == "failure" for event in events):
            events.append(
                TraceEvent(
                    kind="failure",
                    title="Retries exhausted",
                    detail=format_exception(exc),
                    attempt=attempts or None,
                )
            )
        return _failure(
            spec=spec,
            provider=provider,
            schema_key=schema_key,
            provider_key=provider_key,
            model_name=resolved_model,
            started=started,
            events=events,
            error_message="The schema rejected every attempt. The log has each ValidationError.",
            secret=secret,
            attempts=attempts,
        )
    except ValidationError as exc:
        if not any(event.kind == "validation_error" for event in events):
            events.append(
                TraceEvent(
                    kind="validation_error",
                    title="ValidationError",
                    detail=format_exception(exc),
                    fields=field_paths(exc),
                )
            )
        return _failure(
            spec=spec,
            provider=provider,
            schema_key=schema_key,
            provider_key=provider_key,
            model_name=resolved_model,
            started=started,
            events=events,
            error_message="Validation failed and no further retries were available.",
            secret=secret,
        )
    except Exception as exc:
        detail = clip("".join(traceback.format_exception(exc)), MAX_TRACEBACK_CHARS)
        events.append(
            TraceEvent(
                kind="failure",
                title=f"{type(exc).__name__}",
                detail=detail,
            )
        )
        summary = scrub(f"{type(exc).__name__}: {exc}", secret)
        return _failure(
            spec=spec,
            provider=provider,
            schema_key=schema_key,
            provider_key=provider_key,
            model_name=resolved_model,
            started=started,
            events=events,
            error_message=clip(summary, 500),
            secret=secret,
        )


def call_model(client: Any, payload: dict[str, Any]) -> Any:
    """Call Instructor, dropping optional kwargs a provider client does not accept."""
    current = dict(payload)
    while True:
        try:
            return client.create(**current)
        except TypeError as exc:
            text = str(exc)
            removable = [name for name in ("temperature", "model") if name in current and name in text]
            if not removable:
                raise
            for name in removable:
                current.pop(name, None)


def dumps_payload(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def requires_provider_call(
    *,
    source_text: str,
    model_name: str,
    max_retries: int,
    api_key: str,
) -> bool:
    """False when extract() will fail locally, before a provider client is built.

    The UI uses this to skip the model spinner. The key must already be resolved.
    """
    try:
        _check_request(source_text, (model_name or "").strip(), max_retries)
    except ExtractionError:
        return False
    return bool(api_key.strip())


def _create_payload(
    spec: SchemaSpec,
    provider: Provider,
    model_name: str,
    source_text: str,
    max_retries: int,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "response_model": spec.model,
        "messages": [
            {"role": "system", "content": spec.system_prompt},
            {"role": "user", "content": user_prompt(source_text)},
        ],
        "max_retries": max_retries,
        "model": model_name,
    }
    if provider.supports_temperature:
        payload["temperature"] = 0
    return payload


def _check_request(source_text: str, model_name: str, max_retries: int) -> None:
    if not source_text or not source_text.strip():
        raise ExtractionError("Source text is empty. Paste a document or load a sample.")
    if len(source_text) > MAX_SOURCE_CHARS:
        raise ExtractionError(
            f"Source text is {len(source_text)} characters. The limit is {MAX_SOURCE_CHARS}."
        )
    if not model_name:
        raise ExtractionError("Model name is empty.")
    if isinstance(max_retries, bool) or not isinstance(max_retries, int) or not 0 <= max_retries <= 8:
        raise ExtractionError("max_retries must be an integer from 0 through 8.")


def _attempt_count(events: list[TraceEvent], minimum: int = 0) -> int:
    observed = sum(1 for event in events if event.kind == "request")
    return max(observed, minimum)


_RETRY_TYPES: tuple[type[BaseException], ...] | None = None


def _retry_exception_types() -> tuple[type[BaseException], ...]:
    global _RETRY_TYPES
    if _RETRY_TYPES is None:
        _RETRY_TYPES = _load_retry_exception_types()
    return _RETRY_TYPES


def _load_retry_exception_types() -> tuple[type[BaseException], ...]:
    for module_name in ("instructor.core.exceptions", "instructor.exceptions"):
        try:
            module = __import__(module_name, fromlist=["InstructorRetryException"])
        except ImportError:
            continue
        klass = getattr(module, "InstructorRetryException", None)
        if isinstance(klass, type) and issubclass(klass, BaseException):
            return (klass,)
    return ()


def _finish(
    *,
    ok: bool,
    spec: SchemaSpec,
    provider: Provider,
    model_name: str,
    attempts: int,
    started: float,
    data: dict[str, Any] | None,
    checks: list[str],
    events: list[TraceEvent],
    error_message: str | None,
    secret: str,
) -> ExtractionResult:
    scrub_events(events, secret or None)
    safe_error = scrub(error_message, secret or None) if error_message else None
    return ExtractionResult(
        ok=ok,
        schema_key=spec.key,
        schema_label=spec.label,
        provider_key=provider.key,
        provider_label=provider.label,
        model_name=model_name,
        attempts=attempts,
        latency_ms=int((time.perf_counter() - started) * 1000),
        data=data,
        checks=checks,
        events=events,
        error_message=safe_error,
    )


def _failure(
    *,
    spec: SchemaSpec | None,
    provider: Provider | None,
    schema_key: str,
    provider_key: str,
    model_name: str,
    started: float,
    events: list[TraceEvent],
    error_message: str,
    secret: str,
    attempts: int | None = None,
) -> ExtractionResult:
    if spec is None or provider is None:
        scrub_events(events, secret or None)
        return ExtractionResult(
            ok=False,
            schema_key=schema_key,
            schema_label=spec.label if spec else schema_key,
            provider_key=provider_key,
            provider_label=provider.label if provider else provider_key,
            model_name=model_name,
            attempts=attempts if attempts is not None else _attempt_count(events),
            latency_ms=int((time.perf_counter() - started) * 1000),
            data=None,
            checks=[],
            events=events,
            error_message=scrub(error_message, secret or None),
        )
    return _finish(
        ok=False,
        spec=spec,
        provider=provider,
        model_name=model_name,
        attempts=attempts if attempts is not None else _attempt_count(events),
        started=started,
        data=None,
        checks=[],
        events=events,
        error_message=error_message,
        secret=secret,
    )
