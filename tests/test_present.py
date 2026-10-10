from extraction_engine.present import digest_events, format_trace, invoice_view, resume_view
from extraction_engine.tracing import TraceEvent


def test_invoice_view_prices_each_line_and_skips_blank_fields() -> None:
    view = invoice_view(
        {
            "invoice_number": "INV-1",
            "vendor_name": "Northwind",
            "bill_to": "  ",
            "currency": "USD",
            "total_amount": "749.00",
            "line_items": [
                {"description": "Sensor", "quantity": "4", "unit_price": "125.00"},
                {"description": "Freight", "quantity": "1", "unit_price": "64.00"},
            ],
        }
    )
    assert view.total == "749.00"
    assert view.lines[0]["Amount"] == 500.0
    assert view.lines[1]["Amount"] == 64.0
    assert "INV-1" in view.facts.values()
    assert all(value.strip() for value in view.facts.values())
    assert view.notes is None


def test_resume_view_marks_an_open_role() -> None:
    view = resume_view(
        {
            "full_name": "Priya Raman",
            "email": "priya.raman@orbitmail.com",
            "skills": ["Python", " ", "SQL"],
            "years_experience": 5,
            "summary": "Builds extraction pipelines.",
            "work_history": [
                {
                    "employer": "Northline",
                    "title": "Senior ML Engineer",
                    "start_date": "2023-03-01",
                    "end_date": None,
                    "highlights": ["Shipped a model"],
                }
            ],
        }
    )
    assert view.skills == ("Python", "SQL")
    assert view.roles[0].dates == "2023-03-01 — Present"
    assert view.summary == "Builds extraction pipelines."
    assert "priya.raman@orbitmail.com" in view.facts.values()


def test_digest_and_trace_keep_the_rejected_field() -> None:
    events = [
        TraceEvent(kind="request", title="Attempt 1 sent", detail="model=gemini"),
        TraceEvent(
            kind="validation_error",
            title="ValidationError",
            detail="total_amount is 540.00",
            attempt=1,
            fields=("total_amount",),
        ),
        TraceEvent(kind="retry_feedback", title="Correction", detail="Set total_amount to 749.00", attempt=2),
        TraceEvent(kind="request", title="Attempt 2 sent", detail="model=gemini"),
    ]
    digest = digest_events(events)
    assert digest.requests == 2
    assert digest.validation_errors == 1
    assert digest.corrections == 1
    assert digest.rejected_fields == ("total_amount",)

    text = format_trace(
        schema_label="Invoice Extraction",
        provider_label="Google Gemini",
        model_name="gemini-3.5-flash",
        ok=False,
        attempts=2,
        error_message="The schema rejected every attempt.",
        events=events,
    )
    assert "Status: rejected" in text
    assert "fields: total_amount" in text
    assert "540.00" in text
