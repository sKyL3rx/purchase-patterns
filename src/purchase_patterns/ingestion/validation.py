"""Row-count and schema validation for written raw Parquet files.

Validation only reads Parquet footers (row counts, schema and column
statistics), so it stays cheap regardless of the data volume.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from purchase_patterns.ingestion.reader import SheetStats
from purchase_patterns.ingestion.schema import EXPECTED_SHEETS, RAW_SCHEMA, SOURCE_HEADER

PASS = "pass"
FAIL = "fail"


@dataclass(frozen=True)
class SheetOutput:
    """A worksheet that has been streamed into a Parquet file."""

    stats: SheetStats
    parquet_path: Path
    rows_written: int


def _check(name: str, passed: bool, **details: Any) -> dict[str, Any]:
    return {"name": name, "passed": passed, **details}


def _json_value(value: Any) -> Any:
    if isinstance(value, dt.datetime | dt.date):
        return value.isoformat()
    return value


def _column_profile(metadata: pq.FileMetaData, schema: pa.Schema) -> dict[str, Any]:
    null_counts: dict[str, int | None] = {}
    invoice_date_min: Any = None
    invoice_date_max: Any = None
    date_index = schema.get_field_index("invoice_date")

    for column_index, name in enumerate(schema.names):
        total: int | None = 0
        for row_group_index in range(metadata.num_row_groups):
            column = metadata.row_group(row_group_index).column(column_index)
            statistics = column.statistics
            if statistics is None or not statistics.has_null_count or total is None:
                total = None
            else:
                total += statistics.null_count

            if column_index == date_index and statistics is not None and statistics.has_min_max:
                if invoice_date_min is None or statistics.min < invoice_date_min:
                    invoice_date_min = statistics.min
                if invoice_date_max is None or statistics.max > invoice_date_max:
                    invoice_date_max = statistics.max
        null_counts[name] = total

    return {
        "rows": metadata.num_rows,
        "row_groups": metadata.num_row_groups,
        "null_counts": null_counts,
        "invoice_date_min": _json_value(invoice_date_min),
        "invoice_date_max": _json_value(invoice_date_max),
    }


def validate_sheet(output: SheetOutput, expected_schema: pa.Schema = RAW_SCHEMA) -> dict[str, Any]:
    """Validate one sheet's Parquet output against the source counters."""
    stats = output.stats
    with pq.ParquetFile(output.parquet_path) as parquet_file:
        metadata = parquet_file.metadata
        actual_schema = parquet_file.schema_arrow

    checks = [
        _check(
            "header_matches",
            tuple(stats.header) == SOURCE_HEADER,
            expected=list(SOURCE_HEADER),
            actual=[str(value) for value in stats.header],
        ),
        _check(
            "row_count_reconciles",
            stats.data_rows_read == output.rows_written == metadata.num_rows,
            source_rows_read=stats.data_rows_read,
            rows_written=output.rows_written,
            parquet_rows=metadata.num_rows,
        ),
        _check(
            "schema_matches",
            actual_schema.equals(expected_schema),
            expected=str(expected_schema),
            actual=str(actual_schema),
        ),
    ]

    if stats.declared_max_row is None:
        checks.append(
            _check("sheet_dimension_reconciles", True, skipped=True, reason="no dimension")
        )
    else:
        declared_data_rows = stats.declared_max_row - 1
        accounted_rows = stats.data_rows_read + stats.blank_rows_skipped
        checks.append(
            _check(
                "sheet_dimension_reconciles",
                declared_data_rows == accounted_rows,
                declared_data_rows=declared_data_rows,
                data_rows_read=stats.data_rows_read,
                blank_rows_skipped=stats.blank_rows_skipped,
            )
        )

    return {
        "sheet_name": stats.sheet_name,
        "parquet_file": output.parquet_path.name,
        "status": PASS if all(check["passed"] for check in checks) else FAIL,
        "checks": checks,
        "blank_rows_skipped": stats.blank_rows_skipped,
        "profile": _column_profile(metadata, actual_schema),
    }


def build_validation_report(
    outputs: Sequence[SheetOutput],
    *,
    expected_sheets: Sequence[str] = EXPECTED_SHEETS,
    expected_schema: pa.Schema = RAW_SCHEMA,
) -> dict[str, Any]:
    """Build the JSON-serialisable validation report for an ingestion run."""
    sheet_reports = [validate_sheet(output, expected_schema) for output in outputs]

    processed = [output.stats.sheet_name for output in outputs]
    totals = {
        "data_rows_read": sum(output.stats.data_rows_read for output in outputs),
        "rows_written": sum(output.rows_written for output in outputs),
        "parquet_rows": sum(report["profile"]["rows"] for report in sheet_reports),
        "blank_rows_skipped": sum(output.stats.blank_rows_skipped for output in outputs),
    }
    checks = [
        _check(
            "all_expected_sheets_ingested",
            sorted(processed) == sorted(expected_sheets),
            expected=list(expected_sheets),
            actual=processed,
        ),
        _check(
            "total_row_count_reconciles",
            totals["data_rows_read"] == totals["rows_written"] == totals["parquet_rows"],
            **totals,
        ),
    ]

    passed = all(check["passed"] for check in checks) and all(
        report["status"] == PASS for report in sheet_reports
    )
    return {
        "status": PASS if passed else FAIL,
        "checks": checks,
        "totals": totals,
        "sheets": sheet_reports,
    }
