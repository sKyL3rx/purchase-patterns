"""Quality metrics and reconciliation checks for the classification outputs."""

from __future__ import annotations

from typing import Any

import duckdb

from purchase_patterns.quality.schema import EXCLUSION_CODES

PASS = "pass"
FAIL = "fail"


def _check(name: str, passed: bool, **details: Any) -> dict[str, Any]:
    return {"name": name, "passed": passed, **details}


def build_quality_report(con: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    """Aggregate per-rule counts from ``classified_line_items`` / ``valid_purchases``."""
    totals = (
        con.execute(
            """
        SELECT
            count(*) AS classified_rows,
            count(*) FILTER (WHERE is_canonical) AS canonical_rows,
            count(*) FILTER (WHERE NOT is_canonical) AS non_canonical_rows,
            count(*) FILTER (WHERE is_eligible_valid_purchase) AS valid_rows,
            count(*) FILTER (WHERE is_cross_sheet_duplicate) AS cross_sheet_member_rows,
            count(DISTINCT business_key_hash)
                FILTER (WHERE is_cross_sheet_duplicate) AS cross_sheet_groups,
            count(*) FILTER (WHERE is_exact_duplicate) AS exact_duplicate_rows,
            count(*) FILTER (WHERE is_cancellation) AS cancellation_rows,
            count(*) FILTER (WHERE is_accounting_adjustment) AS accounting_adjustment_rows,
            count(*) FILTER (
                WHERE is_non_positive_quantity AND NOT is_cancellation
            ) AS non_positive_quantity_rows,
            count(*) FILTER (WHERE is_non_positive_price) AS non_positive_price_rows,
            count(*) FILTER (WHERE is_missing_customer_id) AS missing_customer_id_rows,
            count(*) FILTER (WHERE is_non_product) AS non_product_rows,
            count(*) FILTER (WHERE is_ambiguous) AS ambiguous_rows,
            count(*) FILTER (WHERE is_invalid_timestamp) AS invalid_timestamp_rows,
            min(invoice_date) AS invoice_date_min,
            max(invoice_date) AS invoice_date_max
        FROM classified_line_items
        """
        )
        .fetchdf()
        .to_dict(orient="records")[0]
    )

    for key in ("invoice_date_min", "invoice_date_max"):
        value = totals[key]
        totals[key] = value.isoformat() if value is not None else None

    exclusion_hits = {
        code: int(
            con.execute(
                """
                SELECT count(*)
                FROM classified_line_items
                WHERE list_contains(exclusion_codes, ?)
                """,
                [code],
            ).fetchone()[0]
        )
        for code in EXCLUSION_CODES
    }

    record_types = {
        str(row[0]): int(row[1])
        for row in con.execute(
            """
            SELECT record_type, count(*)
            FROM classified_line_items
            GROUP BY 1
            ORDER BY 2 DESC
            """
        ).fetchall()
    }

    top_non_product = [
        {"stock_code": row[0], "rows": int(row[1])}
        for row in con.execute(
            """
            SELECT stock_code, count(*) AS n
            FROM classified_line_items
            WHERE is_non_product
            GROUP BY 1
            ORDER BY n DESC
            LIMIT 20
            """
        ).fetchall()
    ]

    cancel_qty = [
        {
            "is_cancellation": bool(row[0]),
            "quantity_sign": row[1],
            "rows": int(row[2]),
        }
        for row in con.execute(
            """
            SELECT
                is_cancellation,
                CASE
                    WHEN quantity < 0 THEN 'negative'
                    WHEN quantity = 0 THEN 'zero'
                    ELSE 'positive'
                END AS quantity_sign,
                count(*)
            FROM classified_line_items
            GROUP BY 1, 2
            ORDER BY 3 DESC
            """
        ).fetchall()
    ]

    valid_stats = (
        con.execute(
            """
        SELECT
            count(*) AS rows,
            count(DISTINCT customer_id) AS customers,
            count(DISTINCT invoice) AS invoices,
            sum(line_amount) AS gross_line_amount,
            min(invoice_date) AS invoice_date_min,
            max(invoice_date) AS invoice_date_max
        FROM valid_purchases
        """
        )
        .fetchdf()
        .to_dict(orient="records")[0]
    )
    for key in ("invoice_date_min", "invoice_date_max"):
        value = valid_stats[key]
        valid_stats[key] = value.isoformat() if value is not None else None
    if valid_stats["gross_line_amount"] is not None:
        valid_stats["gross_line_amount"] = float(valid_stats["gross_line_amount"])

    return {
        "status": PASS,
        "totals": totals,
        "exclusion_code_hits": exclusion_hits,
        "record_types": record_types,
        "top_non_product_stock_codes": top_non_product,
        "cancellation_quantity_crosstab": cancel_qty,
        "valid_purchases": valid_stats,
    }


def build_reconciliation_report(
    con: duckdb.DuckDBPyConnection,
    *,
    raw_rows: int,
    interim_hashes: dict[str, str],
) -> dict[str, Any]:
    """Verify accounting identities between raw, classified, and valid outputs."""
    counts = con.execute(
        """
        SELECT
            count(*) AS classified_rows,
            count(*) FILTER (WHERE is_canonical) AS canonical_rows,
            count(*) FILTER (WHERE NOT is_canonical) AS non_canonical_rows,
            count(*) FILTER (WHERE is_eligible_valid_purchase) AS valid_rows,
            count(*) FILTER (
                WHERE is_canonical AND NOT is_eligible_valid_purchase
            ) AS excluded_canonical_rows,
            count(*) FILTER (
                WHERE is_eligible_valid_purchase AND NOT is_canonical
            ) AS invalid_eligible_rows,
            (SELECT count(*) FROM valid_purchases) AS valid_table_rows,
            (
                SELECT count(DISTINCT business_key_hash) FROM classified_line_items
            ) AS distinct_business_keys
        FROM classified_line_items
        """
    ).fetchone()
    (
        classified_rows,
        canonical_rows,
        non_canonical_rows,
        valid_rows,
        excluded_canonical_rows,
        invalid_eligible_rows,
        valid_table_rows,
        distinct_business_keys,
    ) = counts

    valid_guarantees = con.execute(
        """
        SELECT
            count(*) FILTER (WHERE customer_id IS NULL) AS null_cid,
            count(*) FILTER (WHERE quantity <= 0) AS nonpos_qty,
            count(*) FILTER (WHERE price <= 0) AS nonpos_price,
            count(*) FILTER (WHERE starts_with(invoice, 'C')) AS cancel_invoice,
            count(*) FILTER (WHERE starts_with(invoice, 'A')) AS adjust_invoice,
            count(*) - count(DISTINCT business_key_hash) AS duplicate_keys
        FROM valid_purchases
        """
    ).fetchone()

    checks = [
        _check(
            "raw_equals_classified",
            raw_rows == classified_rows,
            raw_rows=raw_rows,
            classified_rows=classified_rows,
        ),
        _check(
            "classified_splits_canonical",
            classified_rows == canonical_rows + non_canonical_rows,
            classified_rows=classified_rows,
            canonical_rows=canonical_rows,
            non_canonical_rows=non_canonical_rows,
        ),
        _check(
            "canonical_equals_distinct_keys",
            canonical_rows == distinct_business_keys,
            canonical_rows=canonical_rows,
            distinct_business_keys=distinct_business_keys,
        ),
        _check(
            "canonical_splits_valid",
            canonical_rows == valid_rows + excluded_canonical_rows,
            canonical_rows=canonical_rows,
            valid_rows=valid_rows,
            excluded_canonical_rows=excluded_canonical_rows,
        ),
        _check(
            "valid_table_matches_flag",
            valid_rows == valid_table_rows,
            valid_rows=valid_rows,
            valid_table_rows=valid_table_rows,
        ),
        _check(
            "no_eligible_non_canonical",
            invalid_eligible_rows == 0,
            invalid_eligible_rows=invalid_eligible_rows,
        ),
        _check(
            "valid_purchases_guarantees",
            all(v == 0 for v in valid_guarantees),
            null_customer_id=valid_guarantees[0],
            non_positive_quantity=valid_guarantees[1],
            non_positive_price=valid_guarantees[2],
            cancellation_invoices=valid_guarantees[3],
            accounting_invoices=valid_guarantees[4],
            duplicate_business_keys=valid_guarantees[5],
        ),
    ]

    passed = all(check["passed"] for check in checks)
    return {
        "status": PASS if passed else FAIL,
        "checks": checks,
        "counts": {
            "raw_rows": raw_rows,
            "classified_rows": classified_rows,
            "canonical_rows": canonical_rows,
            "non_canonical_rows": non_canonical_rows,
            "valid_rows": valid_rows,
            "excluded_canonical_rows": excluded_canonical_rows,
            "distinct_business_keys": distinct_business_keys,
        },
        "interim_file_sha256": interim_hashes,
    }
