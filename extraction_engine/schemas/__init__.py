"""Pydantic schemas and the catalog the app extracts into."""

from extraction_engine.schemas.invoice import Invoice, LineItem
from extraction_engine.schemas.registry import SchemaSpec, get_schema, schema_from_label, schema_options
from extraction_engine.schemas.resume import CandidateResume, WorkExperience

__all__ = [
    "CandidateResume",
    "Invoice",
    "LineItem",
    "SchemaSpec",
    "WorkExperience",
    "get_schema",
    "schema_from_label",
    "schema_options",
]
