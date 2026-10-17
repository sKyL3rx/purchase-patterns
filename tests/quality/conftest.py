"""Synthetic interim Parquet fixtures covering each quality rule."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from purchase_patterns.ingestion.schema import RAW_SCHEMA

SHEET_2009 = "Year 2009-2010"
SHEET_2010 = "Year 2010-2011"

# Shared business-key row used for cross-sheet overlap and within-sheet dupes.
_OVERLAP = {
    "invoice": "536365",
    "stock_code": "85123A",
    "description": "WHITE HANGING HEART T-LIGHT HOLDER",
    "quantity": 6,
    "invoice_date": dt.datetime(2010, 12, 1, 8, 26),
    "price": 2.55,
    "customer_id": "17850",
    "country": "United Kingdom",
}


def _row(**overrides) -> dict:
    base = {
        "invoice": "489434",
        "stock_code": "85048",
        "description": "GLASS BALL",
        "quantity": 12,
        "invoice_date": dt.datetime(2009, 12, 1, 7, 45),
        "price": 6.95,
        "customer_id": "13085",
        "country": "United Kingdom",
        "source_sheet": SHEET_2009,
        "source_row_number": 2,
    }
    base.update(overrides)
    return base


def build_synthetic_interim_rows() -> list[dict]:
    """Return raw-schema rows exercising every quality rule."""
    return [
        # Normal purchase (eligible)
        _row(source_row_number=2),
        # Within-sheet exact duplicate of normal purchase (non-canonical)
        _row(source_row_number=3),
        # Cross-sheet overlap: prefer 2010-2011
        {**_OVERLAP, "source_sheet": SHEET_2009, "source_row_number": 10},
        {**_OVERLAP, "source_sheet": SHEET_2010, "source_row_number": 5},
        # Cancellation with negative qty
        _row(
            invoice="C489449",
            stock_code="22087",
            description="PAPER BUNTING",
            quantity=-12,
            invoice_date=dt.datetime(2009, 12, 1, 10, 33),
            price=2.95,
            customer_id="16321",
            country="Australia",
            source_row_number=20,
        ),
        # Non-cancel negative quantity
        _row(
            invoice="490000",
            stock_code="22423",
            description="REGENCY CAKESTAND",
            quantity=-1,
            price=12.75,
            customer_id="13085",
            source_row_number=21,
        ),
        # Zero price
        _row(
            invoice="490001",
            stock_code="22424",
            description="FREE SAMPLE",
            quantity=1,
            price=0.0,
            customer_id="13085",
            source_row_number=22,
        ),
        # Accounting adjustment (A + B Adjust)
        _row(
            invoice="A506401",
            stock_code="B",
            description="Adjust bad debt",
            quantity=1,
            price=-53594.36,
            customer_id=None,
            source_row_number=23,
        ),
        # Missing customer_id (otherwise valid product)
        _row(
            invoice="490002",
            stock_code="22425",
            description="GUEST BOOK",
            quantity=2,
            price=3.75,
            customer_id=None,
            source_row_number=24,
        ),
        # Non-product POST
        _row(
            invoice="490003",
            stock_code="POST",
            description="POSTAGE",
            quantity=1,
            price=18.0,
            customer_id="13085",
            source_row_number=25,
        ),
        # Non-product M
        _row(
            invoice="490004",
            stock_code="M",
            description="Manual",
            quantity=1,
            price=10.0,
            customer_id="13085",
            source_row_number=26,
        ),
        # Non-product GIFT
        _row(
            invoice="490005",
            stock_code="GIFT_0001_10",
            description="Gift voucher",
            quantity=1,
            price=10.0,
            customer_id=None,
            source_row_number=27,
        ),
        # Ambiguous cancellation: C + positive quantity
        _row(
            invoice="C496350",
            stock_code="M",
            description="Manual",
            quantity=1,
            price=373.57,
            customer_id=None,
            source_row_number=28,
        ),
        # Second eligible purchase on preferred sheet
        _row(
            invoice="536366",
            stock_code="22633",
            description="HAND WARMER UNION JACK",
            quantity=6,
            invoice_date=dt.datetime(2010, 12, 1, 8, 28),
            price=1.85,
            customer_id="17850",
            source_sheet=SHEET_2010,
            source_row_number=30,
        ),
    ]


def write_interim_parquet(directory: Path, rows: list[dict] | None = None) -> Path:
    """Write synthetic rows as a single interim Parquet file; return the directory."""
    directory.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist(rows or build_synthetic_interim_rows(), schema=RAW_SCHEMA)
    pq.write_table(table, directory / "synthetic.parquet", compression="zstd")
    return directory


@pytest.fixture
def synthetic_interim_dir(tmp_path: Path) -> Path:
    """Interim directory with one synthetic Parquet covering all quality rules."""
    return write_interim_parquet(tmp_path / "interim")


@pytest.fixture
def output_dir(tmp_path: Path) -> Path:
    return tmp_path / "processed"
