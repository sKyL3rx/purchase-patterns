"""End-to-end ingestion of the real workbook (opt-in: ``uv run pytest -m integration``)."""

from __future__ import annotations

from pathlib import Path

import pyarrow.compute as pc
import pyarrow.parquet as pq
import pytest

from purchase_patterns.ingestion import RAW_SCHEMA, ingest_workbook

SOURCE = Path(__file__).resolve().parents[2] / "data" / "raw" / "online_retail_II.xlsx"
EXPECTED_ROWS = {"Year 2009-2010": 525_461, "Year 2010-2011": 541_910}

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not SOURCE.is_file(), reason=f"{SOURCE} is not available"),
]


def test_real_workbook_ingests_and_reconciles(tmp_path):
    result = ingest_workbook(SOURCE, tmp_path)

    assert result.passed, result.validation_report
    report = result.validation_report
    assert report["totals"]["parquet_rows"] == sum(EXPECTED_ROWS.values()) == 1_067_371
    for sheet_name, expected_rows in EXPECTED_ROWS.items():
        path = result.parquet_files[sheet_name]
        assert pq.read_metadata(path).num_rows == expected_rows
        assert pq.read_schema(path).equals(RAW_SCHEMA)

        customer_id = pq.read_table(path, columns=["customer_id"]).column("customer_id")
        assert not pc.any(pc.ends_with(customer_id, ".0")).as_py()
        assert not pc.any(pc.equal(customer_id, "nan")).as_py()
