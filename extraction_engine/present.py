"""Turn a validated record into display data. No Streamlit imports."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from extraction_engine.schemas.invoice import line_amount
from extraction_engine.tracing import TraceEvent


@dataclass(frozen=True)
class InvoiceView:
    currency: str
    total: str
    facts: dict[str, str]
    lines: list[dict[str, float | str | None]]
    notes: str | None


@dataclass(frozen=True)
class RoleView:
    title: str
    employer: str
    dates: str
    highlights: tuple[str, ...]


@dataclass(frozen=True)
class ResumeView:
    facts: dict[str, str]
    skills: tuple[str, ...]
    roles: tuple[RoleView, ...]
    summary: str | None


@dataclass(frozen=True)
class TraceDigest:
    requests: int
    validation_errors: int
    corrections: int
    rejected_fields: tuple[str, ...]


def digest_events(events: Sequence[TraceEvent]) -> TraceDigest:
    fields: list[str] = []
    for event in events:
        if event.kind != "validation_error":
            continue
        for name in event.fields:
            if name not in fields:
                fields.append(name)
    return TraceDigest(
        requests=sum(event.kind == "request" for event in events),
        validation_errors=sum(event.kind == "validation_error" for event in events),
        corrections=sum(event.kind == "retry_feedback" for event in events),
        rejected_fields=tuple(fields),
    )


def format_trace(
    *,
    schema_label: str,
    provider_label: str,
    model_name: str,
    ok: bool,
    attempts: int,
    error_message: str | None,
    events: Sequence[TraceEvent],
) -> str:
    """Plain-text copy of one run, including each ValidationError."""
    lines = [
        f"Schema: {schema_label}",
        f"Provider: {provider_label}",
        f"Model: {model_name}",
        f"Status: {'valid' if ok else 'rejected'}",
        f"Attempts: {attempts}",
    ]
    if error_message:
        lines.append(f"Error: {error_message}")
    lines.append("")
    for index, event in enumerate(events, start=1):
        attempt = f" attempt={event.attempt}" if event.attempt is not None else ""
        lines.append(f"{index}. [{event.kind}] {event.title}{attempt}")
        if event.fields:
            lines.append("fields: " + ", ".join(event.fields))
        if event.detail:
            lines.append(event.detail)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def invoice_view(data: Mapping[str, Any]) -> InvoiceView:
    currency = _text(data.get("currency")) or "—"
    total = _money(data.get("total_amount"))
    facts = _compact(
        {
            ":material/tag: Invoice": data.get("invoice_number"),
            ":material/store: Vendor": data.get("vendor_name"),
            ":material/person: Bill to": data.get("bill_to"),
            ":material/calendar_today: Issued": data.get("issued_on"),
            ":material/event: Due": data.get("due_date"),
            ":material/payments: Terms": data.get("payment_terms"),
            ":material/receipt_long: PO": data.get("purchase_order"),
            ":material/account_balance: Total": f"{total} {currency}".strip(),
        }
    )
    return InvoiceView(
        currency=currency,
        total=total,
        facts=facts,
        lines=_invoice_lines(data.get("line_items")),
        notes=_text(data.get("notes")) or None,
    )


def resume_view(data: Mapping[str, Any]) -> ResumeView:
    years = data.get("years_experience")
    facts = _compact(
        {
            ":material/person: Name": data.get("full_name"),
            ":material/mail: Email": data.get("email"),
            ":material/call: Phone": data.get("phone"),
            ":material/location_on: Location": data.get("location"),
            ":material/work_history: Years": None if years is None else str(years),
        }
    )
    skills = data.get("skills")
    names = tuple(_text(item) for item in skills) if isinstance(skills, list) else ()
    return ResumeView(
        facts=facts,
        skills=tuple(name for name in names if name),
        roles=_roles(data.get("work_history")),
        summary=_text(data.get("summary")) or None,
    )


def _invoice_lines(raw: object) -> list[dict[str, float | str | None]]:
    if not isinstance(raw, list):
        return []
    rows: list[dict[str, float | str | None]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        quantity = _decimal(item.get("quantity"))
        price = _decimal(item.get("unit_price"))
        amount = None
        if quantity is not None and price is not None:
            amount = line_amount(quantity, price)
        rows.append(
            {
                "Description": _text(item.get("description")),
                "Quantity": float(quantity) if quantity is not None else None,
                "Unit price": float(price) if price is not None else None,
                "Amount": float(amount) if amount is not None else None,
            }
        )
    return rows


def _roles(raw: object) -> tuple[RoleView, ...]:
    if not isinstance(raw, list):
        return ()
    roles: list[RoleView] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        end = item.get("end_date")
        end_label = "Present" if end in (None, "") else _text(end)
        start = _text(item.get("start_date")) or "—"
        highlights = item.get("highlights")
        bullets = tuple(_text(line) for line in highlights) if isinstance(highlights, list) else ()
        roles.append(
            RoleView(
                title=_text(item.get("title")) or "Role",
                employer=_text(item.get("employer")) or "—",
                dates=f"{start} — {end_label}",
                highlights=tuple(line for line in bullets if line),
            )
        )
    return tuple(roles)


def _compact(pairs: dict[str, object]) -> dict[str, str]:
    facts: dict[str, str] = {}
    for label, value in pairs.items():
        text = _text(value)
        if text:
            facts[label] = text
    return facts


def _text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _money(value: object) -> str:
    amount = _decimal(value)
    if amount is None:
        return _text(value) or "—"
    return f"{amount:.2f}"


def _decimal(value: object) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value).strip())
    except Exception:
        return None
