from __future__ import annotations

import datetime as dt

import pytest

from purchase_patterns.ingestion.schema import (
    COLUMN_CONVERTERS,
    COLUMN_MAP,
    RAW_SCHEMA,
    SOURCE_HEADER,
    CellConversionError,
    sheet_slug,
    to_customer_id,
    to_float,
    to_int,
    to_str_id,
    to_text,
    to_timestamp,
)


def test_schema_covers_every_source_column_plus_lineage():
    mapped = [COLUMN_MAP[name] for name in SOURCE_HEADER]
    assert RAW_SCHEMA.names == [*mapped, "source_sheet", "source_row_number"]
    assert set(COLUMN_CONVERTERS) == set(mapped)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (489434, "489434"),
        ("C489449", "C489449"),
        (85048.0, "85048"),
        ("79323P", "79323P"),
        (" 123 ", " 123 "),
        (None, None),
    ],
)
def test_to_str_id(value, expected):
    assert to_str_id(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (13085, "13085"),
        (13085.0, "13085"),
        ("12345", "12345"),
        (None, None),
    ],
)
def test_to_customer_id_never_produces_float_suffix_or_nan(value, expected):
    assert to_customer_id(value) == expected


@pytest.mark.parametrize("value", [12.5, float("nan"), float("inf"), True, dt.datetime(2010, 1, 1)])
def test_to_customer_id_rejects_non_identifiers(value):
    with pytest.raises(CellConversionError):
        to_customer_id(value)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (" WHITE CHERRY LIGHTS", " WHITE CHERRY LIGHTS"),
        ("", ""),
        (None, None),
        (12, "12"),
        (1.5, "1.5"),
    ],
)
def test_to_text_keeps_strings_verbatim(value, expected):
    assert to_text(value) == expected


@pytest.mark.parametrize(("value", "expected"), [(12, 12), (-12, -12), (6.0, 6), (None, None)])
def test_to_int(value, expected):
    assert to_int(value) == expected


@pytest.mark.parametrize("value", [1.5, "12", True, float("nan")])
def test_to_int_rejects_non_integers(value):
    with pytest.raises(CellConversionError):
        to_int(value)


@pytest.mark.parametrize(
    ("value", "expected"), [(6.95, 6.95), (18, 18.0), (0.0, 0.0), (-1.5, -1.5), (None, None)]
)
def test_to_float(value, expected):
    result = to_float(value)
    assert result == expected
    assert result is None or isinstance(result, float)


@pytest.mark.parametrize("value", ["6.95", False])
def test_to_float_rejects_non_numbers(value):
    with pytest.raises(CellConversionError):
        to_float(value)


def test_to_timestamp_accepts_naive_datetime():
    value = dt.datetime(2009, 12, 1, 7, 45)
    assert to_timestamp(value) == value
    assert to_timestamp(None) is None


@pytest.mark.parametrize(
    "value",
    ["2009-12-01 07:45", 40148.32, dt.datetime(2009, 12, 1, tzinfo=dt.UTC)],
)
def test_to_timestamp_rejects_strings_numbers_and_aware_values(value):
    with pytest.raises(CellConversionError):
        to_timestamp(value)


def test_sheet_slug():
    assert sheet_slug("Year 2009-2010") == "year_2009_2010"
    assert sheet_slug("Year 2010-2011") == "year_2010_2011"
