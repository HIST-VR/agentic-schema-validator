"""Invoice schema. The total check is the business rule that drives retries."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Annotated

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    ValidationInfo,
    WithJsonSchema,
    field_validator,
)

from extraction_engine.schemas.parsing import CENT, parse_decimal, parse_optional_date

# Number, not Decimal's string pattern. Some providers reject the lookahead
# inside Pydantic's default decimal schema.
DecimalAmount = Annotated[
    Decimal,
    BeforeValidator(parse_decimal),
    WithJsonSchema({"type": "number"}),
]
OptionalDate = Annotated[date | None, BeforeValidator(parse_optional_date)]


class LineItem(BaseModel):
    """One billed row. Line math is quantity times unit price, in cents."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    description: str = Field(min_length=1, description="What was sold, as printed on the line.")
    quantity: DecimalAmount = Field(gt=0, description="Units billed. Must be greater than zero.")
    unit_price: DecimalAmount = Field(ge=0, description="Price for one unit, in major currency units.")


def line_amount(quantity: Decimal, unit_price: Decimal) -> Decimal:
    return (quantity * unit_price).quantize(CENT, rounding=ROUND_HALF_UP)


def sum_line_amounts(items: list[LineItem]) -> Decimal:
    total = sum((line_amount(item.quantity, item.unit_price) for item in items), Decimal("0.00"))
    return total.quantize(CENT, rounding=ROUND_HALF_UP)


def explain_lines(items: list[LineItem]) -> str:
    parts = [
        (
            f"{item.description} ({item.quantity} × {item.unit_price} = "
            f"{line_amount(item.quantity, item.unit_price)})"
        )
        for item in items
    ]
    return "; ".join(parts)


class Invoice(BaseModel):
    """A payable invoice whose printed total must match the line items.

    `line_items` is declared before `total_amount` on purpose. Pydantic's
    field validator can only see fields that have already been validated.
    """

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    invoice_number: str = Field(min_length=1, description="Invoice identifier as printed.")
    vendor_name: str = Field(min_length=1, description="Party that issued the invoice.")
    bill_to: str | None = Field(default=None, description="Customer being billed. Null if unstated.")
    currency: str = Field(description="ISO 4217 currency code such as USD, EUR, or GBP.")
    issued_on: OptionalDate = Field(default=None, description="Issue date. Null if unstated.")
    due_date: OptionalDate = Field(default=None, description="Due date. Null if unstated.")
    line_items: list[LineItem] = Field(min_length=1, description="Billed rows copied from the document.")
    total_amount: DecimalAmount = Field(
        ge=0,
        description=(
            "Amount due printed on the document. Copy that printed figure. "
            "Do not replace it with a sum calculated from the lines."
        ),
    )
    payment_terms: str | None = Field(default=None, description="Terms such as Net 15. Null if unstated.")
    purchase_order: str | None = Field(default=None, description="PO number. Null if unstated.")
    notes: str | None = Field(default=None, description="Short leftover clerk notes. Null if none.")

    @field_validator("currency")
    @classmethod
    def currency_code(cls, value: str) -> str:
        code = value.strip().upper()
        if len(code) != 3 or not code.isalpha():
            raise ValueError(
                f"currency {value!r} is not a 3-letter ISO code. Use a code such as USD, EUR, or GBP."
            )
        return code

    @field_validator("due_date")
    @classmethod
    def due_not_before_issue(cls, value: date | None, info: ValidationInfo) -> date | None:
        issued = info.data.get("issued_on")
        if value is not None and isinstance(issued, date) and value < issued:
            raise ValueError(
                f"due_date {value.isoformat()} is before issued_on {issued.isoformat()}. "
                "Correct the dates from the source, or use null when the due date is unstated."
            )
        return value

    @field_validator("total_amount")
    @classmethod
    def total_matches_line_items(cls, value: Decimal, info: ValidationInfo) -> Decimal:
        raw_items = info.data.get("line_items")
        if not raw_items:
            return value
        items = [item for item in raw_items if isinstance(item, LineItem)]
        if len(items) != len(raw_items):
            return value
        computed = sum_line_amounts(items)
        if value != computed:
            raise ValueError(
                f"total_amount is {value} but the line items sum to {computed}. "
                f"Each line is quantity × unit_price, rounded half-up to cents, then summed. "
                f"Lines: {explain_lines(items)}. "
                f"Set total_amount to {computed}. Do not add a balancing line. "
                "Keep each line unless its quantity or unit price disagrees with the source text."
            )
        return value

    def acceptance_summary(self) -> list[str]:
        computed = sum_line_amounts(self.line_items)
        return [
            f"{len(self.line_items)} line items sum to {computed} {self.currency}.",
            f"total_amount {self.total_amount} matches the line-item sum.",
        ]
