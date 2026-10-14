"""Shared fixtures: small synthetic Online Retail II workbooks built with openpyxl."""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import openpyxl
import pytest

from purchase_patterns.ingestion.schema import SOURCE_HEADER

Row = Sequence[Any]
WorkbookFactory = Callable[..., Path]

BLANK_ROW: tuple[None, ...] = (None,) * len(SOURCE_HEADER)

SYNTHETIC_ROWS: dict[str, list[Row]] = {
    "Year 2009-2010": [
        (489434, 85048, "15CM CHRISTMAS GLASS BALL 20 LIGHTS", 12,
         dt.datetime(2009, 12, 1, 7, 45), 6.95, 13085, "United Kingdom"),
        (489434, "79323W", " WHITE CHERRY LIGHTS", 12,
         dt.datetime(2009, 12, 1, 7, 45), 6.75, 13085.0, "United Kingdom"),
        ("C489449", "22087", "PAPER BUNTING WHITE LACE", -12,
         dt.datetime(2009, 12, 1, 10, 33), 2.95, 16321, "Australia"),
        BLANK_ROW,
        (489450, "POST", None, 1,
         dt.datetime(2009, 12, 1, 10, 40), 18, None, "France"),
    ],
    "Year 2010-2011": [
        (536365, "85123A", "WHITE HANGING HEART T-LIGHT HOLDER", 6,
         dt.datetime(2010, 12, 1, 8, 26), 2.55, 17850, "United Kingdom"),
        (536365, 71053, "WHITE METAL LANTERN", 6,
         dt.datetime(2010, 12, 1, 8, 26), 3.39, 17850, "United Kingdom"),
        (536366, "22633", "HAND WARMER UNION JACK", 6,
         dt.datetime(2010, 12, 1, 8, 28), 0.0, "12345", "United Kingdom"),
        (536365, "85123A", "WHITE HANGING HEART T-LIGHT HOLDER", 6,
         dt.datetime(2010, 12, 1, 8, 26), 2.55, 17850, "United Kingdom"),
    ],
}  # fmt: skip


def write_workbook(
    path: Path,
    sheets: dict[str, list[Row]],
    header: Row = SOURCE_HEADER,
) -> Path:
    """Write ``sheets`` (name -> data rows) to ``path`` with ``header`` on each sheet."""
    workbook = openpyxl.Workbook()
    workbook.remove(workbook.active)
    for sheet_name, rows in sheets.items():
        worksheet = workbook.create_sheet(sheet_name)
        worksheet.append(list(header))
        for row in rows:
            worksheet.append(list(row))
    workbook.save(path)
    return path


@pytest.fixture
def synthetic_rows() -> dict[str, list[Row]]:
    """Data rows (without header) used by ``synthetic_workbook``."""
    return {name: list(rows) for name, rows in SYNTHETIC_ROWS.items()}


@pytest.fixture
def make_workbook(tmp_path: Path) -> WorkbookFactory:
    """Factory building a workbook in ``tmp_path``; defaults to the synthetic rows."""

    def factory(
        sheets: dict[str, list[Row]] | None = None,
        *,
        header: Row = SOURCE_HEADER,
        name: str = "online_retail_II.xlsx",
    ) -> Path:
        return write_workbook(tmp_path / name, sheets or SYNTHETIC_ROWS, header)

    return factory


@pytest.fixture
def synthetic_workbook(make_workbook: WorkbookFactory) -> Path:
    """A two-sheet workbook mirroring the real source's structure and quirks."""
    return make_workbook()
