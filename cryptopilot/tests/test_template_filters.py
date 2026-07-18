"""Tests app/api/template_filters.py — compact_number/compact_usd (Market Stats)."""

from app.api.template_filters import _compact_number, _compact_usd


def test_compact_number_trillions():
    assert _compact_number(1_320_000_000_000) == "1.32T"


def test_compact_number_billions():
    assert _compact_number(28_500_000_000) == "28.50B"


def test_compact_number_millions():
    assert _compact_number(19_800_000) == "19.80M"


def test_compact_number_below_thousand_uses_grouped_decimal():
    assert _compact_number(842.5) == "842.50"


def test_compact_number_negative_keeps_sign():
    assert _compact_number(-2_500_000) == "-2.50M"


def test_compact_number_none_is_dash():
    assert _compact_number(None) == "—"


def test_compact_usd_prefixes_dollar():
    assert _compact_usd(1_320_000_000_000) == "$1.32T"


def test_compact_usd_none_is_dash():
    assert _compact_usd(None) == "—"
