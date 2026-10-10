"""Headless UI run. No browser and no model call."""

from datetime import date
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from extraction_engine.engine import ExtractionResult
from extraction_engine.providers import GOOGLE
from extraction_engine.schemas.invoice import Invoice
from extraction_engine.schemas.resume import CandidateResume
from extraction_engine.tracing import TraceEvent

APP_PATH = Path(__file__).resolve().parents[1] / "app.py"


def _quiet_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("dotenv.load_dotenv", lambda *args, **kwargs: False)
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY", "XAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)


def _app(monkeypatch: pytest.MonkeyPatch) -> AppTest:
    _quiet_env(monkeypatch)
    app = AppTest.from_file(APP_PATH, default_timeout=30)
    app.run()
    assert not app.exception
    return app


def test_sample_load_clear_and_missing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _app(monkeypatch)
    assert app.selectbox(key="provider").value == GOOGLE.label
    assert app.selectbox(key="model-google").value == GOOGLE.default_model
    assert app.selectbox(key="agent").value == "Invoice Extraction"
    assert app.button(key="extract").proto.disabled

    app.button(key="load_sample").click().run()
    assert not app.exception
    assert "INV-2041" in app.text_area(key="raw_text").value
    assert "540.00" in app.text_area(key="raw_text").value
    assert any("540.00" in item.value for item in app.info)
    assert not app.button(key="extract").proto.disabled

    app.text_input(key="model-override-google").set_value("gemini-custom").run()
    assert any("gemini-custom" in item.value for item in app.caption)

    app.button(key="extract").click().run()
    assert not app.exception
    assert app.error
    assert "GEMINI_API_KEY" in app.error[0].value
    assert len(app.session_state["history"]) == 1

    app.button(key="extract").click().run()
    assert len(app.session_state["history"]) == 2
    assert app.button(key="restore-1")

    app.button(key="clear_text").click().run()
    assert not app.exception
    assert app.text_area(key="raw_text").value == ""
    assert app.button(key="extract").proto.disabled

    app.selectbox(key="agent").set_value("Resume Parsing").run()
    app.button(key="load_sample").click().run()
    assert not app.exception
    assert "Priya Raman" in app.text_area(key="raw_text").value
    assert "priya.raman@" in app.text_area(key="raw_text").value


def test_accepted_invoice_renders_the_record_and_the_log(monkeypatch: pytest.MonkeyPatch) -> None:
    invoice = Invoice.model_validate(
        {
            "invoice_number": "INV-2041",
            "vendor_name": "Northwind Supply Co.",
            "currency": "USD",
            "line_items": [
                {"description": "Industrial sensor pack", "quantity": 4, "unit_price": "125.00"},
            ],
            "total_amount": "500.00",
        }
    )
    result = ExtractionResult(
        ok=True,
        schema_key="invoice",
        schema_label="Invoice Extraction",
        provider_key="google",
        provider_label="Google Gemini",
        model_name="gemini-3.5-flash",
        attempts=2,
        latency_ms=1800,
        data=invoice.model_dump(mode="json"),
        checks=["1 line item sums to 500.00 USD."],
        events=[
            TraceEvent(
                kind="validation_error",
                title="ValidationError",
                detail="total_amount is 540.00",
                attempt=1,
                fields=("total_amount",),
            ),
            TraceEvent(
                kind="retry_feedback",
                title="Correction fed back",
                detail="Set total_amount to 500.00",
                attempt=2,
            ),
            TraceEvent(kind="success", title="Validation passed", detail="Accepted Invoice.", attempt=2),
        ],
        error_message=None,
    )
    app = _app(monkeypatch)
    app.session_state["result"] = result
    app.run()
    assert not app.exception
    assert app.success
    assert app.metric[0].value == "Valid"
    assert app.metric[1].value == "2"
    labels = [item.label for item in app.expander]
    assert any("ValidationError" in label for label in labels)
    assert any("540.00" in item.value for item in app.code)
    frame = app.dataframe[0].value
    assert "Industrial sensor pack" in set(frame["Description"])
    assert app.download_button(key="download-json")
    assert app.download_button(key="download-trace")

    app.selectbox(key="agent").set_value("Resume Parsing").run()
    assert not app.exception
    assert app.warning
    assert "Invoice Extraction" in app.warning[0].value


def test_accepted_resume_renders_an_open_role(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("extraction_engine.schemas.resume.current_date", lambda: date(2026, 10, 5))
    resume = CandidateResume.model_validate(
        {
            "full_name": "Priya Raman",
            "email": "priya.raman@orbitmail.com",
            "skills": ["Python"],
            "years_experience": 5,
            "work_history": [
                {
                    "employer": "Northline Analytics",
                    "title": "Senior ML Engineer",
                    "start_date": "2021-06-01",
                    "end_date": None,
                    "highlights": ["Shipped a model"],
                }
            ],
        }
    )
    result = ExtractionResult(
        ok=True,
        schema_key="resume",
        schema_label="Resume Parsing",
        provider_key="google",
        provider_label="Google Gemini",
        model_name="gemini-3.5-flash",
        attempts=1,
        latency_ms=400,
        data=resume.model_dump(mode="json"),
        checks=["Email passed."],
        events=[TraceEvent(kind="success", title="Validation passed", detail="Accepted.", attempt=1)],
        error_message=None,
    )
    app = _app(monkeypatch)
    app.session_state["result"] = result
    app.session_state["agent"] = "Resume Parsing"
    app.run()
    assert not app.exception
    assert any("Senior ML Engineer" in item.value for item in app.markdown)
    assert any("Present" in item.value for item in app.caption)
    assert not app.warning
