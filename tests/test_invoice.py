from decimal import Decimal

import pytest
from pydantic import ValidationError

from extraction_engine.samples import INVOICE_LINES, INVOICE_PRINTED_TOTAL
from extraction_engine.schemas.invoice import Invoice


def _payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "invoice_number": "INV-2041",
        "vendor_name": "Northwind Supply Co.",
        "bill_to": "Acme Robotics LLC",
        "currency": "usd",
        "issued_on": "03/14/2026",
        "line_items": [
            {"description": line.description, "quantity": line.quantity, "unit_price": line.unit_price}
            for line in INVOICE_LINES
        ],
        "total_amount": "749.00",
        "payment_terms": "Net 15",
        "purchase_order": "8891",
    }
    payload.update(overrides)
    return payload


def test_valid_invoice_normalizes_currency_and_date() -> None:
    invoice = Invoice.model_validate(_payload())
    assert invoice.currency == "USD"
    assert invoice.issued_on is not None and invoice.issued_on.isoformat() == "2026-03-14"
    assert invoice.due_date is None
    assert invoice.total_amount == Decimal("749.00")
    assert invoice.acceptance_summary()[1].startswith("total_amount 749.00")


def test_printed_sample_total_fails_and_names_the_reconciled_sum() -> None:
    expected = sum((line.quantity * line.unit_price for line in INVOICE_LINES), Decimal("0.00"))
    assert expected != INVOICE_PRINTED_TOTAL
    with pytest.raises(ValidationError) as caught:
        Invoice.model_validate(_payload(total_amount=INVOICE_PRINTED_TOTAL))
    message = str(caught.value)
    assert "total_amount" in message
    assert f"{expected:.2f}" in message
    Invoice.model_validate(_payload(total_amount=expected))


def test_due_date_before_issue_is_rejected() -> None:
    with pytest.raises(ValidationError, match="due_date"):
        Invoice.model_validate(_payload(due_date="2026-03-01"))


def test_currency_and_quantity_rules() -> None:
    with pytest.raises(ValidationError, match="ISO"):
        Invoice.model_validate(_payload(currency="dollars"))
    with pytest.raises(ValidationError):
        Invoice.model_validate(
            _payload(
                line_items=[{"description": "Sensor", "quantity": 0, "unit_price": "10.00"}],
                total_amount="0.00",
            )
        )


def test_total_validator_sees_line_items() -> None:
    names = list(Invoice.model_fields)
    assert names.index("line_items") < names.index("total_amount")


def test_money_schema_is_a_number_without_lookahead() -> None:
    schema = Invoice.model_json_schema()
    assert schema["properties"]["total_amount"]["type"] == "number"
    assert schema["$defs"]["LineItem"]["properties"]["unit_price"]["type"] == "number"
    _assert_no_lookahead(schema)


def _assert_no_lookahead(node: object) -> None:
    if isinstance(node, dict):
        pattern = node.get("pattern")
        if isinstance(pattern, str):
            assert "(?" not in pattern
        for value in node.values():
            _assert_no_lookahead(value)
    elif isinstance(node, list):
        for item in node:
            _assert_no_lookahead(item)
