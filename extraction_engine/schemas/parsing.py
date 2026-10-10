"""Coercion helpers shared by the extraction schemas.

Validators raise ValueError with a sentence a model can act on. Instructor
feeds that sentence back on the next attempt.
"""

from __future__ import annotations

import math
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

CENT = Decimal("0.01")

_MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}

_PRESENT = {"present", "current", "now", "ongoing", "today", "n/a", "na", "none", "null"}
_NUMERIC_DATE = re.compile(r"^(\d{1,4})([./-])(\d{1,2})\2(\d{1,4})$")
_MONTH_YEAR = re.compile(r"^([A-Za-z]+)\s+(\d{4})$")
_MONTH_DAY_YEAR = re.compile(r"^([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})$")
_DAY_MONTH_YEAR = re.compile(r"^(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})$")
_YEAR_MONTH = re.compile(r"^(\d{4})-(\d{1,2})$")
_MONTH_SLASH_YEAR = re.compile(r"^(\d{1,2})/(\d{4})$")


def parse_decimal(value: object) -> Decimal:
    """Parse a money-like value and round half-up to cents."""
    if isinstance(value, bool):
        raise ValueError("Amount must be a number such as 18.50.")
    if isinstance(value, Decimal):
        amount = value
    elif isinstance(value, int):
        amount = Decimal(value)
    elif isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Amount must be a finite number.")
        amount = Decimal(str(value))
    elif isinstance(value, str):
        text = value.strip()
        text = text.replace(",", "")
        text = re.sub(r"(?i)\b(usd|eur|gbp|cad|aud)\b", "", text)
        text = text.replace("$", "").replace("€", "").replace("£", "").strip()
        if not text:
            raise ValueError("Amount is empty. Send a numeric value such as 18.50.")
        try:
            amount = Decimal(text)
        except InvalidOperation as exc:
            raise ValueError(
                f"Amount {value!r} is not a number. Send a numeric value such as 18.50."
            ) from exc
    else:
        raise ValueError(f"Amount {value!r} is not a number. Send a numeric value such as 18.50.")
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)


def parse_flexible_date(value: object, *, allow_present: bool = False) -> date | None:
    """Parse ISO dates and a few forms that show up in scanned documents.

    Numeric dates with both parts at or below 12 are read as month/day/year.
    A month and year with no day becomes the first of that month.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, bool) or isinstance(value, (int, float)):
        raise ValueError("Dates must be strings in YYYY-MM-DD format, not numbers.")
    if not isinstance(value, str):
        raise ValueError(f"Unsupported date value {value!r}. Use YYYY-MM-DD.")

    text = value.strip()
    if not text:
        if allow_present:
            return None
        raise ValueError("Date is empty. Use YYYY-MM-DD.")

    lowered = text.lower().rstrip(".")
    if lowered in _PRESENT:
        if allow_present:
            return None
        raise ValueError(f"Date {text!r} is not a calendar date. Use YYYY-MM-DD.")

    iso_match = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", text)
    if iso_match:
        return _build_date(int(iso_match.group(1)), int(iso_match.group(2)), int(iso_match.group(3)), text)

    year_month = _YEAR_MONTH.fullmatch(text)
    if year_month:
        return _build_date(int(year_month.group(1)), int(year_month.group(2)), 1, text)

    month_slash_year = _MONTH_SLASH_YEAR.fullmatch(text)
    if month_slash_year:
        return _build_date(int(month_slash_year.group(2)), int(month_slash_year.group(1)), 1, text)

    if re.fullmatch(r"\d{4}", text):
        return date(int(text), 1, 1)

    month_day_year = _MONTH_DAY_YEAR.fullmatch(text)
    if month_day_year:
        month = _month_number(month_day_year.group(1), text)
        return _build_date(int(month_day_year.group(3)), month, int(month_day_year.group(2)), text)

    day_month_year = _DAY_MONTH_YEAR.fullmatch(text)
    if day_month_year:
        month = _month_number(day_month_year.group(2), text)
        return _build_date(int(day_month_year.group(3)), month, int(day_month_year.group(1)), text)

    month_year = _MONTH_YEAR.fullmatch(text)
    if month_year:
        month = _month_number(month_year.group(1), text)
        return _build_date(int(month_year.group(2)), month, 1, text)

    numeric = _NUMERIC_DATE.fullmatch(text)
    if numeric:
        first, _separator, second, third = numeric.groups()
        year, month, day = _split_numeric_date(first, second, third, text)
        return _build_date(year, month, day, text)

    raise ValueError(f"Unparsed date {text!r}. Use YYYY-MM-DD.")


def parse_required_date(value: object) -> date:
    parsed = parse_flexible_date(value, allow_present=False)
    if parsed is None:
        raise ValueError("A calendar date is required. Use YYYY-MM-DD.")
    return parsed


def parse_optional_date(value: object) -> date | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    return parse_flexible_date(value, allow_present=False)


def parse_end_date(value: object) -> date | None:
    """End dates may be null when the role is current."""
    return parse_flexible_date(value, allow_present=True)


def _month_number(name: str, original: str) -> int:
    month = _MONTHS.get(name.lower())
    if month is None:
        raise ValueError(f"Unparsed date {original!r}. Use YYYY-MM-DD.")
    return month


def _split_numeric_date(first: str, second: str, third: str, original: str) -> tuple[int, int, int]:
    if len(first) == 4:
        return int(first), int(second), int(third)
    if len(third) == 4:
        month = int(first)
        day = int(second)
        if month > 12 and day <= 12:
            month, day = day, month
        return int(third), month, day
    raise ValueError(f"Unparsed date {original!r}. Use YYYY-MM-DD.")


def _build_date(year: int, month: int, day: int, original: str) -> date:
    try:
        return date(year, month, day)
    except ValueError as exc:
        raise ValueError(f"Unparsed date {original!r}. Use YYYY-MM-DD.") from exc
