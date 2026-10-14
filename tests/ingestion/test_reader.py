from __future__ import annotations

import pyarrow as pa
import pytest

from purchase_patterns.ingestion.reader import (
    SheetStats,
    iter_sheet_batches,
    list_sheet_names,
)
from purchase_patterns.ingestion.schema import (
    EXPECTED_SHEETS,
    RAW_SCHEMA,
    SOURCE_HEADER,
    IngestionError,
)

SHEET = "Year 2009-2010"


def test_list_sheet_names(synthetic_workbook):
    assert list_sheet_names(synthetic_workbook) == list(EXPECTED_SHEETS)


def test_small_batch_size_yields_multiple_batches_with_correct_totals(synthetic_workbook):
    stats = SheetStats(sheet_name=SHEET)
    batches = list(iter_sheet_batches(synthetic_workbook, SHEET, batch_size=2, stats=stats))

    assert [batch.num_rows for batch in batches] == [2, 2]
    assert all(batch.schema.equals(RAW_SCHEMA) for batch in batches)
    assert stats.data_rows_read == 4
    assert stats.blank_rows_skipped == 1
    assert stats.batches == 2
    assert stats.header == list(SOURCE_HEADER)
    assert stats.declared_max_row == 6


def test_source_row_numbers_are_excel_rows_and_skip_blank_rows(synthetic_workbook):
    table = pa.Table.from_batches(
        list(iter_sheet_batches(synthetic_workbook, SHEET, batch_size=10))
    )

    assert table.column("source_row_number").to_pylist() == [2, 3, 4, 6]
    assert set(table.column("source_sheet").to_pylist()) == {SHEET}


def test_header_mismatch_raises(make_workbook, synthetic_rows):
    header = [*SOURCE_HEADER[:-2], "CustomerID", "Country"]
    path = make_workbook(synthetic_rows, header=header)

    with pytest.raises(IngestionError, match="header"):
        list(iter_sheet_batches(path, SHEET))


def test_missing_sheet_raises(synthetic_workbook):
    with pytest.raises(IngestionError, match="not found"):
        list(iter_sheet_batches(synthetic_workbook, "Year 2011-2012"))


def test_bad_cell_error_reports_sheet_row_and_column(make_workbook, synthetic_rows):
    rows = synthetic_rows[SHEET]
    rows[1] = (*rows[1][:3], "twelve", *rows[1][4:])
    path = make_workbook({SHEET: rows})

    with pytest.raises(IngestionError, match=r"row 3 column 'Quantity'.*'twelve'"):
        list(iter_sheet_batches(path, SHEET))


def test_values_beyond_expected_columns_raise(make_workbook, synthetic_rows):
    rows = synthetic_rows[SHEET]
    rows[0] = (*rows[0], "unexpected")
    path = make_workbook({SHEET: rows})

    with pytest.raises(IngestionError, match="beyond column 8"):
        list(iter_sheet_batches(path, SHEET))


def test_invalid_batch_size_raises(synthetic_workbook):
    with pytest.raises(ValueError, match="batch_size"):
        list(iter_sheet_batches(synthetic_workbook, SHEET, batch_size=0))
