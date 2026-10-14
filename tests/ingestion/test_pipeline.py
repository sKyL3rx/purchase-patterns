from __future__ import annotations

import datetime as dt
import json

import pyarrow.parquet as pq
import pytest

from purchase_patterns.ingestion import __main__ as cli
from purchase_patterns.ingestion import pipeline
from purchase_patterns.ingestion.pipeline import (
    METADATA_FILE,
    VALIDATION_REPORT_FILE,
    file_sha256,
    ingest_workbook,
)
from purchase_patterns.ingestion.reader import SheetStats
from purchase_patterns.ingestion.schema import (
    EXPECTED_SHEETS,
    RAW_SCHEMA,
    SOURCE_HEADER,
    IngestionError,
)
from purchase_patterns.ingestion.validation import SheetOutput, build_validation_report

SHEET_2009, SHEET_2010 = EXPECTED_SHEETS


@pytest.fixture
def output_dir(tmp_path):
    return tmp_path / "interim"


@pytest.fixture
def result(synthetic_workbook, output_dir):
    return ingest_workbook(synthetic_workbook, output_dir, batch_size=2)


def _read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_publishes_expected_files_without_leftovers(result, output_dir):
    assert result.passed
    assert result.output_dir == output_dir / "online_retail_ii"
    assert sorted(path.name for path in result.output_dir.iterdir()) == [
        METADATA_FILE,
        VALIDATION_REPORT_FILE,
        "year_2009_2010.parquet",
        "year_2010_2011.parquet",
    ]
    assert [path.name for path in output_dir.iterdir()] == ["online_retail_ii"]


def test_row_counts_and_schema(result):
    rows = {sheet: pq.read_metadata(path).num_rows for sheet, path in result.parquet_files.items()}
    assert rows == {SHEET_2009: 4, SHEET_2010: 4}
    for path in result.parquet_files.values():
        assert pq.read_schema(path).equals(RAW_SCHEMA)


def test_raw_values_are_preserved_without_cleaning(result):
    records = pq.read_table(result.parquet_files[SHEET_2009]).to_pylist()

    assert records == [
        {
            "invoice": "489434",
            "stock_code": "85048",
            "description": "15CM CHRISTMAS GLASS BALL 20 LIGHTS",
            "quantity": 12,
            "invoice_date": dt.datetime(2009, 12, 1, 7, 45),
            "price": 6.95,
            "customer_id": "13085",
            "country": "United Kingdom",
            "source_sheet": SHEET_2009,
            "source_row_number": 2,
        },
        {
            "invoice": "489434",
            "stock_code": "79323W",
            "description": " WHITE CHERRY LIGHTS",
            "quantity": 12,
            "invoice_date": dt.datetime(2009, 12, 1, 7, 45),
            "price": 6.75,
            "customer_id": "13085",
            "country": "United Kingdom",
            "source_sheet": SHEET_2009,
            "source_row_number": 3,
        },
        {
            "invoice": "C489449",
            "stock_code": "22087",
            "description": "PAPER BUNTING WHITE LACE",
            "quantity": -12,
            "invoice_date": dt.datetime(2009, 12, 1, 10, 33),
            "price": 2.95,
            "customer_id": "16321",
            "country": "Australia",
            "source_sheet": SHEET_2009,
            "source_row_number": 4,
        },
        {
            "invoice": "489450",
            "stock_code": "POST",
            "description": None,
            "quantity": 1,
            "invoice_date": dt.datetime(2009, 12, 1, 10, 40),
            "price": 18.0,
            "customer_id": None,
            "country": "France",
            "source_sheet": SHEET_2009,
            "source_row_number": 6,
        },
    ]


def test_duplicates_zero_prices_and_string_ids_are_kept(result):
    table = pq.read_table(result.parquet_files[SHEET_2010])

    assert table.column("customer_id").to_pylist() == ["17850", "17850", "12345", "17850"]
    assert table.column("price").to_pylist() == [2.55, 3.39, 0.0, 2.55]
    assert table.column("stock_code").to_pylist() == ["85123A", "71053", "22633", "85123A"]
    source_columns = [name for name in RAW_SCHEMA.names if not name.startswith("source_")]
    first, *_, last = table.select(source_columns).to_pylist()
    assert first == last


def test_validation_report_contents(result):
    report = _read_json(result.validation_report_path)

    assert report == result.validation_report
    assert report["status"] == "pass"
    assert report["totals"] == {
        "data_rows_read": 8,
        "rows_written": 8,
        "parquet_rows": 8,
        "blank_rows_skipped": 1,
    }
    assert all(check["passed"] for check in report["checks"])

    sheet_2009 = report["sheets"][0]
    assert sheet_2009["sheet_name"] == SHEET_2009
    assert sheet_2009["parquet_file"] == "year_2009_2010.parquet"
    assert sheet_2009["blank_rows_skipped"] == 1
    assert {check["name"] for check in sheet_2009["checks"]} == {
        "header_matches",
        "row_count_reconciles",
        "schema_matches",
        "sheet_dimension_reconciles",
    }
    assert all(check["passed"] for check in sheet_2009["checks"])
    profile = sheet_2009["profile"]
    assert profile["rows"] == 4
    assert profile["row_groups"] == 2
    assert profile["null_counts"]["description"] == 1
    assert profile["null_counts"]["customer_id"] == 1
    assert profile["null_counts"]["invoice"] == 0
    assert profile["invoice_date_min"] == "2009-12-01T07:45:00"
    assert profile["invoice_date_max"] == "2009-12-01T10:40:00"


def test_metadata_contents(result, synthetic_workbook):
    metadata = _read_json(result.metadata_path)

    assert metadata["run_id"] == result.run_id
    assert metadata["status"] == "pass"
    assert metadata["dataset"] == "online_retail_ii"
    assert metadata["source"]["file_name"] == synthetic_workbook.name
    assert metadata["source"]["sha256"] == file_sha256(synthetic_workbook)
    assert metadata["source"]["size_bytes"] == synthetic_workbook.stat().st_size
    assert metadata["parameters"] == {
        "batch_size": 2,
        "sheets": list(EXPECTED_SHEETS),
        "compression": "zstd",
    }
    assert set(metadata["environment"]) == {"python", "purchase_patterns", "openpyxl", "pyarrow"}
    assert [(o["sheet_name"], o["file"], o["rows"]) for o in metadata["outputs"]] == [
        (SHEET_2009, "year_2009_2010.parquet", 4),
        (SHEET_2010, "year_2010_2011.parquet", 4),
    ]
    for output in metadata["outputs"]:
        assert output["sha256"] == file_sha256(result.output_dir / output["file"])
    assert [field["name"] for field in metadata["schema"]] == RAW_SCHEMA.names
    assert metadata["duration_seconds"] >= 0


def test_rerun_replaces_previous_output(result, synthetic_workbook, output_dir):
    second = ingest_workbook(synthetic_workbook, output_dir)

    assert second.passed
    assert second.run_id != result.run_id
    assert _read_json(second.metadata_path)["run_id"] == second.run_id
    assert [path.name for path in output_dir.iterdir()] == ["online_retail_ii"]


def test_bad_cell_fails_and_leaves_previous_output_untouched(
    result, make_workbook, synthetic_rows, output_dir
):
    rows = synthetic_rows[SHEET_2010]
    rows[2] = (*rows[2][:6], 12.5, rows[2][7])
    bad_workbook = make_workbook({**synthetic_rows, SHEET_2010: rows}, name="bad.xlsx")
    published_before = result.parquet_files[SHEET_2009].read_bytes()

    with pytest.raises(IngestionError, match=r"row 4 column 'Customer ID'"):
        ingest_workbook(bad_workbook, output_dir)

    assert _read_json(result.metadata_path)["run_id"] == result.run_id
    assert result.parquet_files[SHEET_2009].read_bytes() == published_before
    assert [path.name for path in output_dir.iterdir()] == ["online_retail_ii"]


def test_missing_sheet_fails_before_writing(make_workbook, synthetic_rows, output_dir):
    workbook = make_workbook({SHEET_2009: synthetic_rows[SHEET_2009]})

    with pytest.raises(IngestionError, match="Missing expected sheets"):
        ingest_workbook(workbook, output_dir)

    assert not output_dir.exists()


def test_missing_source_raises(tmp_path, output_dir):
    with pytest.raises(IngestionError, match="not found"):
        ingest_workbook(tmp_path / "absent.xlsx", output_dir)


def test_failed_validation_is_kept_aside_and_not_published(
    synthetic_workbook, output_dir, monkeypatch
):
    def failing_report(*args, **kwargs):
        report = build_validation_report(*args, **kwargs)
        return {**report, "status": "fail"}

    monkeypatch.setattr(pipeline, "build_validation_report", failing_report)

    result = ingest_workbook(synthetic_workbook, output_dir)

    assert not result.passed
    assert result.output_dir.name == f".failed-online_retail_ii-{result.run_id}"
    assert _read_json(result.validation_report_path)["status"] == "fail"
    assert not (output_dir / "online_retail_ii").exists()


def test_validation_detects_row_count_mismatch(result):
    stats = SheetStats(
        sheet_name=SHEET_2009,
        header=list(SOURCE_HEADER),
        declared_max_row=6,
        data_rows_read=4,
        blank_rows_skipped=1,
    )
    output = SheetOutput(stats=stats, parquet_path=result.parquet_files[SHEET_2009], rows_written=3)

    report = build_validation_report([output], expected_sheets=[SHEET_2009])

    assert report["status"] == "fail"
    failed = {c["name"] for c in report["sheets"][0]["checks"] if not c["passed"]}
    assert failed == {"row_count_reconciles"}


def test_cli_exit_codes(synthetic_workbook, make_workbook, synthetic_rows, output_dir):
    assert cli.main(["--source", str(synthetic_workbook), "--output-dir", str(output_dir)]) == 0
    assert (output_dir / "online_retail_ii" / "year_2009_2010.parquet").is_file()

    bad_header = make_workbook(
        synthetic_rows, header=[*SOURCE_HEADER[:-1], "Nation"], name="bad_header.xlsx"
    )
    assert cli.main(["--source", str(bad_header), "--output-dir", str(output_dir)]) == 1
    absent = output_dir / "absent.xlsx"
    assert cli.main(["--source", str(absent), "--output-dir", str(output_dir)]) == 1
