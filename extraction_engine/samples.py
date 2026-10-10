"""Dirty source texts. The printed figures are meant to fail a business rule."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class SampleLine:
    description: str
    quantity: Decimal
    unit_price: Decimal


@dataclass(frozen=True)
class SampleRole:
    employer: str
    title: str
    start: date
    end: date | None
    highlight: str


INVOICE_LINES: tuple[SampleLine, ...] = (
    SampleLine("Industrial sensor pack", Decimal("4"), Decimal("125.00")),
    SampleLine("Mounting brackets", Decimal("10"), Decimal("18.50")),
    SampleLine("Expedited freight", Decimal("1"), Decimal("64.00")),
)
INVOICE_NUMBER = "INV-2041"
INVOICE_VENDOR = "Northwind Supply Co."
INVOICE_BILL_TO = "Acme Robotics LLC"
INVOICE_PRINTED_TOTAL = Decimal("540.00")
INVOICE_ISSUED_ON = "03/14/2026"
INVOICE_TERMS = "Net 15"
INVOICE_PO = "8891"

RESUME_NAME = "Priya Raman"
RESUME_TRUNCATED_EMAIL = "priya.raman@"
RESUME_EMAIL = "priya.raman@orbitmail.com"
RESUME_STATED_YEARS = 10
RESUME_PHONE = "415-555-0148"
RESUME_LOCATION = "Oakland, CA"
RESUME_SKILLS: tuple[str, ...] = ("Python", "PyTorch", "SQL", "dbt", "Airflow")
RESUME_ROLES: tuple[SampleRole, ...] = (
    SampleRole(
        "Northline Analytics",
        "Senior ML Engineer",
        date(2023, 3, 1),
        None,
        "Shipped ranking models and owned the feature store.",
    ),
    SampleRole(
        "Harbor Clinic",
        "Data Analyst",
        date(2021, 6, 1),
        date(2023, 2, 1),
        "Built SQL dashboards for clinic operations.",
    ),
)


def _qty(value: Decimal) -> str:
    integral = value.to_integral()
    if value == integral:
        return str(integral)
    return f"{value:.2f}"


def invoice_sample_text() -> str:
    rows = "\n".join(
        f"- {line.description} | qty {_qty(line.quantity)} | unit price ${line.unit_price:.2f}"
        for line in INVOICE_LINES
    )
    return f"""*** AP inbox scan. OCR confidence is mixed. Do not clean this up by hand. ***

INV number: {INVOICE_NUMBER}
Vendor: {INVOICE_VENDOR}
Bill to: {INVOICE_BILL_TO}
Currency printed as "usd"
Invoice date {INVOICE_ISSUED_ON}
No due date on the page.

Lines (clerk handwriting):
{rows}

A margin worksheet adds the extensions and is then crossed out.
AMOUNT DUE box is filled in as ${INVOICE_PRINTED_TOTAL:.2f}
Terms: {INVOICE_TERMS}. PO {INVOICE_PO}.
"""


_MONTH_NAMES = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


def _month_year(value: date) -> str:
    return f"{_MONTH_NAMES[value.month - 1]} {value.year}"


def resume_sample_text() -> str:
    role_lines = []
    for index, role in enumerate(RESUME_ROLES, start=1):
        end = "present" if role.end is None else _month_year(role.end)
        start = _month_year(role.start)
        role_lines.append(
            f"{index}) {role.employer} — {role.title} — {start} to {end}\n   {role.highlight}"
        )
    roles = "\n".join(role_lines)
    skill_sentence = ", ".join(RESUME_SKILLS[:-1]) + f", and {RESUME_SKILLS[-1]}"
    return f"""TALENT FORM (messy export)

Full name: {RESUME_NAME}
Old email field: {RESUME_TRUNCATED_EMAIL}
Signature block email: {RESUME_EMAIL}
Phone: {RESUME_PHONE}
Location: {RESUME_LOCATION}

Summary: ML engineer who ships ranking systems.
Form field years_experience was typed as {RESUME_STATED_YEARS}.

Work:
{roles}
Unpaid campus aide, summer 2019, is listed and marked "not employment — do not include".

Skills blurb: "I live in {skill_sentence} every day, plus the usual docs."
"""


INVOICE_SAMPLE_NOTE = (
    f"The amount due is printed as {INVOICE_PRINTED_TOTAL:.2f}. "
    "The lines do not add up to that figure, and the page has no due date. "
    "The agent is told to copy the printed total. The total_amount validator rejects the copy "
    "and sends the reconciled sum back for the next attempt."
)

RESUME_SAMPLE_NOTE = (
    f"The form states {RESUME_STATED_YEARS} years. The listed jobs do not span that long, "
    f"and an older email field is truncated beside {RESUME_EMAIL}. "
    "The agent is told to copy the stated years. The tenure validator rejects the mismatch."
)
