from datetime import date
from decimal import Decimal

import pytest

from extraction_engine.schemas.parsing import parse_decimal, parse_end_date, parse_flexible_date, parse_required_date


def test_parse_decimal_strips_currency_and_rounds() -> None:
    assert parse_decimal("$1,250.00") == Decimal("1250.00")
    assert parse_decimal("18.5") == Decimal("18.50")
    assert parse_decimal("10.005") == Decimal("10.01")
    assert parse_decimal(4) == Decimal("4.00")


def test_parse_decimal_rejects_blank_and_words() -> None:
    with pytest.raises(ValueError, match="empty"):
        parse_decimal(" $ ")
    with pytest.raises(ValueError, match="not a number"):
        parse_decimal("twelve")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026-03-14", date(2026, 3, 14)),
        ("03/14/2026", date(2026, 3, 14)),
        ("2026/03/14", date(2026, 3, 14)),
        ("March 14, 2026", date(2026, 3, 14)),
        ("14 March 2026", date(2026, 3, 14)),
        ("March 2023", date(2023, 3, 1)),
        ("2021-06", date(2021, 6, 1)),
        ("06/2021", date(2021, 6, 1)),
        ("2019", date(2019, 1, 1)),
    ],
)
def test_parse_flexible_date(raw: str, expected: date) -> None:
    assert parse_flexible_date(raw) == expected


def test_present_is_only_an_end_date() -> None:
    assert parse_end_date("present") is None
    assert parse_end_date("") is None
    with pytest.raises(ValueError):
        parse_required_date("present")


def test_unparsed_date_names_the_expected_format() -> None:
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        parse_flexible_date("not a date")
