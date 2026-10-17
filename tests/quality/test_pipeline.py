from __future__ import annotations

import json

import pyarrow.parquet as pq
import pytest

from purchase_patterns.quality import __main__ as cli
from purchase_patterns.quality import run_quality_pipeline
from purchase_patterns.quality.schema import (
    CLASSIFIED_FILE,
    METADATA_FILE,
    QUALITY_REPORT_FILE,
    RECONCILIATION_FILE,
    RULE_VERSION,
    VALID_PURCHASES_FILE,
    QualityError,
)

SHEET_2010 = "Year 2010-2011"


def _read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _interim_row_count(interim_dir) -> int:
    return sum(pq.read_metadata(path).num_rows for path in interim_dir.glob("*.parquet"))


@pytest.fixture
def result(synthetic_interim_dir, output_dir):
    return run_quality_pipeline(synthetic_interim_dir, output_dir)


def test_publishes_expected_files(result, output_dir):
    assert result.passed
    assert result.output_dir == output_dir / "quality"
    names = sorted(path.name for path in result.output_dir.iterdir())
    assert names == sorted(
        [
            CLASSIFIED_FILE,
            VALID_PURCHASES_FILE,
            QUALITY_REPORT_FILE,
            RECONCILIATION_FILE,
            METADATA_FILE,
        ]
    )


def test_no_silent_drops_and_one_canonical_per_key(result, synthetic_interim_dir):
    input_rows = _interim_row_count(synthetic_interim_dir)
    classified = pq.read_table(result.classified_path)
    assert classified.num_rows == input_rows

    table = classified.to_pandas()
    assert table["is_canonical"].sum() == table["business_key_hash"].nunique()
    assert (table.groupby("business_key_hash")["is_canonical"].sum() == 1).all()


def test_cross_sheet_prefers_2010_sheet(result):
    table = pq.read_table(result.classified_path).to_pandas()
    overlap = table[table["invoice"] == "536365"]
    assert len(overlap) == 2
    assert overlap["is_cross_sheet_duplicate"].all()
    winners = overlap[overlap["is_canonical"]]
    assert len(winners) == 1
    assert winners.iloc[0]["source_sheet"] == SHEET_2010
    assert winners.iloc[0]["canonical_source_sheet"] == SHEET_2010


def test_within_sheet_duplicate_flagged(result):
    table = pq.read_table(result.classified_path).to_pandas()
    dupes = table[table["invoice"] == "489434"]
    assert len(dupes) == 2
    assert dupes["is_canonical"].sum() == 1
    assert dupes["is_exact_duplicate"].sum() == 1
    loser = dupes[~dupes["is_canonical"]].iloc[0]
    assert "not_canonical" in list(loser["exclusion_codes"])


def test_record_types_and_exclusion_codes(result):
    table = pq.read_table(result.classified_path).to_pandas()

    cancel = table[table["invoice"] == "C489449"].iloc[0]
    assert cancel["record_type"] == "cancellation"
    assert cancel["is_cancellation"]
    assert "cancellation" in list(cancel["exclusion_codes"])
    assert not cancel["is_eligible_valid_purchase"]

    ret = table[table["invoice"] == "490000"].iloc[0]
    assert ret["record_type"] == "return_or_adjustment"
    assert "non_positive_quantity" in list(ret["exclusion_codes"])

    zero = table[table["invoice"] == "490001"].iloc[0]
    assert "non_positive_price" in list(zero["exclusion_codes"])

    adjust = table[table["invoice"] == "A506401"].iloc[0]
    assert adjust["record_type"] == "accounting_adjustment"
    assert "accounting_adjustment" in list(adjust["exclusion_codes"])

    missing = table[table["invoice"] == "490002"].iloc[0]
    assert "missing_customer_id" in list(missing["exclusion_codes"])

    post = table[table["invoice"] == "490003"].iloc[0]
    assert post["record_type"] == "non_product"
    assert "non_product_stock_code" in list(post["exclusion_codes"])

    ambiguous = table[table["invoice"] == "C496350"].iloc[0]
    assert ambiguous["record_type"] == "ambiguous"
    assert "ambiguous_cancellation" in list(ambiguous["exclusion_codes"])


def test_valid_purchases_only_eligible_canonical(result):
    classified = pq.read_table(result.classified_path).to_pandas()
    valid = pq.read_table(result.valid_purchases_path).to_pandas()

    eligible = classified[classified["is_eligible_valid_purchase"]]
    assert len(valid) == len(eligible) == 3
    assert set(valid["invoice"]) == {"489434", "536365", "536366"}
    assert valid["customer_id"].notna().all()
    assert (valid["quantity"] > 0).all()
    assert (valid["price"] > 0).all()
    assert ~valid["invoice"].str.startswith("C").any()
    assert ~valid["invoice"].str.startswith("A").any()
    assert valid["business_key_hash"].is_unique
    assert (valid["rule_version"] == RULE_VERSION).all()


def test_reconciliation_and_metadata(result):
    recon = _read_json(result.reconciliation_path)
    quality = _read_json(result.quality_report_path)
    metadata = _read_json(result.metadata_path)

    assert recon["status"] == "pass"
    assert all(check["passed"] for check in recon["checks"])
    assert recon["counts"]["classified_rows"] == pq.read_table(result.classified_path).num_rows
    assert quality["valid_purchases"]["rows"] == 3
    assert metadata["rule_version"] == RULE_VERSION
    assert metadata["status"] == "pass"


def test_rerun_replaces_output(result, synthetic_interim_dir, output_dir):
    second = run_quality_pipeline(synthetic_interim_dir, output_dir)
    assert second.passed
    assert second.run_id != result.run_id
    assert [path.name for path in output_dir.iterdir()] == ["quality"]


def test_missing_interim_raises(tmp_path, output_dir):
    with pytest.raises(QualityError, match="not found"):
        run_quality_pipeline(tmp_path / "missing", output_dir)


def test_cli_exit_codes(synthetic_interim_dir, output_dir, tmp_path):
    assert (
        cli.main(["--interim-dir", str(synthetic_interim_dir), "--output-dir", str(output_dir)])
        == 0
    )
    assert (output_dir / "quality" / CLASSIFIED_FILE).is_file()
    assert (
        cli.main(["--interim-dir", str(tmp_path / "absent"), "--output-dir", str(output_dir)]) == 1
    )
