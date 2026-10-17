"""End-to-end quality pipeline on real interim Parquet (``-m integration``)."""

from __future__ import annotations

from pathlib import Path

import pyarrow.parquet as pq
import pytest

from purchase_patterns.quality import run_quality_pipeline

INTERIM = Path(__file__).resolve().parents[2] / "data" / "interim" / "online_retail_ii"
EXPECTED_RAW = 1_067_371
EXPECTED_CANONICAL = 1_033_036
EXPECTED_CROSS_SHEET_GROUPS = 22_202
EXPECTED_VALID = 776_579

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not any(INTERIM.glob("*.parquet")),
        reason=f"{INTERIM} has no Parquet files",
    ),
]


def test_real_interim_quality_pipeline(tmp_path):
    result = run_quality_pipeline(INTERIM, tmp_path)

    assert result.passed, result.reconciliation_report
    counts = result.reconciliation_report["counts"]
    assert counts["classified_rows"] == EXPECTED_RAW
    assert counts["canonical_rows"] == EXPECTED_CANONICAL
    assert counts["valid_rows"] == EXPECTED_VALID
    assert counts["distinct_business_keys"] == EXPECTED_CANONICAL

    quality = result.quality_report
    assert quality["totals"]["cross_sheet_groups"] == EXPECTED_CROSS_SHEET_GROUPS

    classified = pq.read_table(result.classified_path)
    assert classified.num_rows == EXPECTED_RAW

    valid = pq.read_table(result.valid_purchases_path).to_pandas()
    assert len(valid) == EXPECTED_VALID
    assert valid["customer_id"].notna().all()
    assert (valid["quantity"] > 0).all()
    assert (valid["price"] > 0).all()
    assert ~valid["invoice"].astype(str).str.startswith("C").any()
    assert ~valid["invoice"].astype(str).str.startswith("A").any()
    assert valid["business_key_hash"].is_unique

    # Known non-product codes remain auditable in classified output.
    classified_df = classified.to_pandas()
    assert (classified_df["stock_code"] == "POST").any()
    assert (classified_df["is_cancellation"]).any()
    assert (classified_df["is_missing_customer_id"]).any()
