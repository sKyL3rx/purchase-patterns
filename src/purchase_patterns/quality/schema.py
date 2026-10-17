"""Contracts, constants, and schemas for the data-quality stage."""

from __future__ import annotations

import pyarrow as pa

RULE_VERSION = "quality_v1"
DATASET_NAME = "quality"
PREFERRED_SHEET = "Year 2010-2011"

INTERIM_PARQUET_GLOB = "*.parquet"
CLASSIFIED_FILE = "transactions_classified.parquet"
VALID_PURCHASES_FILE = "valid_purchases.parquet"
QUALITY_REPORT_FILE = "_quality_report.json"
RECONCILIATION_FILE = "_reconciliation.json"
METADATA_FILE = "_quality_metadata.json"

NON_PRODUCT_STOCK_CODES: frozenset[str] = frozenset(
    {
        "POST",
        "DOT",
        "M",
        "D",
        "S",
        "B",
        "C2",
        "CRUK",
        "BANK CHARGES",
        "PADS",
        "AMAZONFEE",
        "ADJUST",
        "ADJUST2",
    }
)

NON_PRODUCT_PREFIXES: tuple[str, ...] = ("GIFT", "TEST", "DCGS")

EXCLUSION_CODES: tuple[str, ...] = (
    "not_canonical",
    "cancellation",
    "accounting_adjustment",
    "non_positive_quantity",
    "non_positive_price",
    "missing_customer_id",
    "non_product_stock_code",
    "ambiguous_cancellation",
    "invalid_invoice_date",
    "missing_key",
)

RECORD_TYPES: tuple[str, ...] = (
    "purchase",
    "cancellation",
    "return_or_adjustment",
    "accounting_adjustment",
    "non_product",
    "ambiguous",
    "invalid",
)

RAW_COLUMNS: tuple[str, ...] = (
    "invoice",
    "stock_code",
    "description",
    "quantity",
    "invoice_date",
    "price",
    "customer_id",
    "country",
    "source_sheet",
    "source_row_number",
)

CLASSIFIED_SCHEMA: pa.Schema = pa.schema(
    [
        pa.field("invoice", pa.string()),
        pa.field("stock_code", pa.string()),
        pa.field("description", pa.string()),
        pa.field("quantity", pa.int64()),
        pa.field("invoice_date", pa.timestamp("us")),
        pa.field("price", pa.float64()),
        pa.field("customer_id", pa.string()),
        pa.field("country", pa.string()),
        pa.field("source_sheet", pa.string()),
        pa.field("source_row_number", pa.int32()),
        pa.field("business_key_hash", pa.string(), nullable=False),
        pa.field("duplicate_group_size", pa.int32(), nullable=False),
        pa.field("is_canonical", pa.bool_(), nullable=False),
        pa.field("canonical_source_sheet", pa.string(), nullable=False),
        pa.field("canonical_source_row_number", pa.int32(), nullable=False),
        pa.field("is_cross_sheet_duplicate", pa.bool_(), nullable=False),
        pa.field("is_exact_duplicate", pa.bool_(), nullable=False),
        pa.field("is_cancellation", pa.bool_(), nullable=False),
        pa.field("is_accounting_adjustment", pa.bool_(), nullable=False),
        pa.field("is_non_positive_quantity", pa.bool_(), nullable=False),
        pa.field("is_non_positive_price", pa.bool_(), nullable=False),
        pa.field("is_missing_customer_id", pa.bool_(), nullable=False),
        pa.field("is_non_product", pa.bool_(), nullable=False),
        pa.field("is_ambiguous", pa.bool_(), nullable=False),
        pa.field("is_invalid_timestamp", pa.bool_(), nullable=False),
        pa.field("record_type", pa.string(), nullable=False),
        pa.field("exclusion_codes", pa.list_(pa.string()), nullable=False),
        pa.field("is_eligible_valid_purchase", pa.bool_(), nullable=False),
        pa.field("line_amount", pa.float64()),
        pa.field("description_trimmed", pa.string()),
        pa.field("is_uk", pa.bool_()),
        pa.field("rule_version", pa.string(), nullable=False),
    ]
)

VALID_PURCHASES_SCHEMA: pa.Schema = pa.schema(
    [
        pa.field("invoice", pa.string()),
        pa.field("stock_code", pa.string()),
        pa.field("description", pa.string()),
        pa.field("quantity", pa.int64()),
        pa.field("invoice_date", pa.timestamp("us")),
        pa.field("price", pa.float64()),
        pa.field("customer_id", pa.string(), nullable=False),
        pa.field("country", pa.string()),
        pa.field("line_amount", pa.float64()),
        pa.field("source_sheet", pa.string(), nullable=False),
        pa.field("source_row_number", pa.int32(), nullable=False),
        pa.field("business_key_hash", pa.string(), nullable=False),
        pa.field("is_uk", pa.bool_()),
        pa.field("rule_version", pa.string(), nullable=False),
    ]
)


class QualityError(RuntimeError):
    """Raised when the quality pipeline cannot run or reconciliation fails hard."""


def is_non_product_stock_code(stock_code: str | None) -> bool:
    """Return True when ``stock_code`` matches the R07 deny-list / prefixes."""
    if stock_code is None:
        return False
    upper = stock_code.upper()
    if upper in NON_PRODUCT_STOCK_CODES:
        return True
    return any(upper.startswith(prefix) for prefix in NON_PRODUCT_PREFIXES)
