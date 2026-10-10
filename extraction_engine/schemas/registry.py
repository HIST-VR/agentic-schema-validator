"""Schema catalog used by the UI and the CLI."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel

from extraction_engine.errors import ExtractionError
from extraction_engine.prompts import INVOICE_SYSTEM, RESUME_SYSTEM
from extraction_engine.samples import (
    INVOICE_SAMPLE_NOTE,
    RESUME_SAMPLE_NOTE,
    invoice_sample_text,
    resume_sample_text,
)
from extraction_engine.schemas.invoice import Invoice
from extraction_engine.schemas.resume import CandidateResume


@dataclass(frozen=True)
class SchemaSpec:
    key: str
    label: str
    blurb: str
    model: type[BaseModel]
    system_prompt: str
    sample_text: str
    sample_note: str
    rules: tuple[str, ...]


INVOICE_SPEC = SchemaSpec(
    key="invoice",
    label="Invoice Extraction",
    blurb="Reconciles every line against the printed total.",
    model=Invoice,
    system_prompt=INVOICE_SYSTEM,
    sample_text=invoice_sample_text(),
    sample_note=INVOICE_SAMPLE_NOTE,
    rules=(
        "At least one line item, with quantity above zero and a unit price of zero or more.",
        "Currency is a 3-letter ISO code.",
        "A due date, when present, is on or after the issue date.",
        "total_amount equals the cent-rounded sum of quantity × unit price.",
    ),
)

RESUME_SPEC = SchemaSpec(
    key="resume",
    label="Resume Parsing",
    blurb="Checks the email and whether stated tenure matches the jobs.",
    model=CandidateResume,
    system_prompt=RESUME_SYSTEM,
    sample_text=resume_sample_text(),
    sample_note=RESUME_SAMPLE_NOTE,
    rules=(
        "Email must be a real mailbox address. Deliverability DNS is not checked.",
        "Each role's end date is on or after its start date. A current role has no end date.",
        "At least one skill name.",
        "years_experience is within one year of the calendar span of the work history.",
    ),
)

SCHEMAS: dict[str, SchemaSpec] = {
    INVOICE_SPEC.key: INVOICE_SPEC,
    RESUME_SPEC.key: RESUME_SPEC,
}


def schema_options() -> list[SchemaSpec]:
    return [INVOICE_SPEC, RESUME_SPEC]


def get_schema(key: str) -> SchemaSpec:
    try:
        return SCHEMAS[key]
    except KeyError as exc:
        known = ", ".join(SCHEMAS)
        raise ExtractionError(f"Unknown schema {key!r}. Choose one of: {known}.") from exc


def schema_from_label(label: str) -> SchemaSpec:
    for spec in schema_options():
        if spec.label == label:
            return spec
    known = ", ".join(spec.label for spec in schema_options())
    raise ExtractionError(f"Unknown extraction agent {label!r}. Choose one of: {known}.")
