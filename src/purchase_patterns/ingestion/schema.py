"""Source contract and explicit cell converters for the Online Retail II workbook.

The raw layer keeps every source value as-is. Converters only change the
*representation* of a cell (for example an Excel integer ``13085`` becomes the
string ``"13085"``); they never trim, filter, deduplicate or impute.
"""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Callable
from typing import Any

import pyarrow as pa

DATASET_NAME = "online_retail_ii"

EXPECTED_SHEETS: tuple[str, ...] = ("Year 2009-2010", "Year 2010-2011")

SOURCE_HEADER: tuple[str, ...] = (
    "Invoice",
    "StockCode",
    "Description",
    "Quantity",
    "InvoiceDate",
    "Price",
    "Customer ID",
    "Country",
)

COLUMN_MAP: dict[str, str] = {
    "Invoice": "invoice",
    "StockCode": "stock_code",
    "Description": "description",
    "Quantity": "quantity",
    "InvoiceDate": "invoice_date",
    "Price": "price",
    "Customer ID": "customer_id",
    "Country": "country",
}

SOURCE_SHEET_COLUMN = "source_sheet"
SOURCE_ROW_COLUMN = "source_row_number"

RAW_SCHEMA: pa.Schema = pa.schema(
    [
        pa.field("invoice", pa.string()),
        pa.field("stock_code", pa.string()),
        pa.field("description", pa.string()),
        pa.field("quantity", pa.int64()),
        pa.field("invoice_date", pa.timestamp("us")),
        pa.field("price", pa.float64()),
        pa.field("customer_id", pa.string()),
        pa.field("country", pa.string()),
        pa.field(SOURCE_SHEET_COLUMN, pa.string(), nullable=False),
        pa.field(SOURCE_ROW_COLUMN, pa.int32(), nullable=False),
    ]
)


class IngestionError(RuntimeError):
    """Raised when the source workbook violates the ingestion contract."""


class CellConversionError(ValueError):
    """Raised when a single cell value cannot be converted to its target type."""


def _reject(value: Any, target: str) -> CellConversionError:
    return CellConversionError(f"cannot convert {value!r} ({type(value).__name__}) to {target}")


def _integral_float_to_int(value: float, target: str) -> int:
    if not math.isfinite(value) or not value.is_integer():
        raise _reject(value, target)
    return int(value)


def to_str_id(value: Any) -> str | None:
    """Convert an identifier cell (invoice, stock code) to a string.

    Integers and integral floats are rendered without a decimal suffix so that
    ``85048`` and ``85048.0`` both become ``"85048"``. Strings are kept verbatim.
    """
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        raise _reject(value, "identifier string")
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(_integral_float_to_int(value, "identifier string"))
    raise _reject(value, "identifier string")


def to_customer_id(value: Any) -> str | None:
    """Convert a ``Customer ID`` cell to a nullable string.

    Excel stores customer IDs as numbers, so a naive float column would turn
    ``13085`` into ``"13085.0"``. Missing cells stay ``None`` (never ``"nan"``)
    and non-integral numbers are rejected instead of being silently rounded.
    """
    return to_str_id(value)


def to_text(value: Any) -> str | None:
    """Convert a free-text cell (description, country) to a string, unmodified."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        raise _reject(value, "text")
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return repr(value)
    raise _reject(value, "text")


def to_int(value: Any) -> int | None:
    """Convert a numeric cell to an integer, rejecting fractional values."""
    if value is None:
        return None
    if isinstance(value, bool):
        raise _reject(value, "int64")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return _integral_float_to_int(value, "int64")
    raise _reject(value, "int64")


def to_float(value: Any) -> float | None:
    """Convert a numeric cell to a float."""
    if value is None:
        return None
    if isinstance(value, bool):
        raise _reject(value, "float64")
    if isinstance(value, int | float):
        return float(value)
    raise _reject(value, "float64")


def to_timestamp(value: Any) -> dt.datetime | None:
    """Convert a date cell to a naive ``datetime``.

    The source has no timezone information, so timezone-aware values are
    rejected rather than being implicitly shifted.
    """
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        if value.tzinfo is not None:
            raise _reject(value, "naive timestamp")
        return value
    raise _reject(value, "naive timestamp")


COLUMN_CONVERTERS: dict[str, Callable[[Any], Any]] = {
    "invoice": to_str_id,
    "stock_code": to_str_id,
    "description": to_text,
    "quantity": to_int,
    "invoice_date": to_timestamp,
    "price": to_float,
    "customer_id": to_customer_id,
    "country": to_text,
}


def sheet_slug(sheet_name: str) -> str:
    """Return a filesystem-friendly name, e.g. ``"Year 2009-2010"`` -> ``"year_2009_2010"``."""
    slug = "".join(ch if ch.isalnum() else "_" for ch in sheet_name.lower())
    return "_".join(part for part in slug.split("_") if part)
