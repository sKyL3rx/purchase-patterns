"""Command-line entry point: ``uv run python -m purchase_patterns.ingestion``."""

from __future__ import annotations

import argparse
import logging
from collections.abc import Sequence
from pathlib import Path

from purchase_patterns.ingestion.pipeline import ingest_workbook
from purchase_patterns.ingestion.reader import DEFAULT_BATCH_SIZE
from purchase_patterns.ingestion.schema import IngestionError

logger = logging.getLogger("purchase_patterns.ingestion")

DEFAULT_SOURCE = Path("data/raw/online_retail_II.xlsx")
DEFAULT_OUTPUT_DIR = Path("data/interim")


def find_project_root(start: Path | None = None) -> Path:
    """Return the nearest ancestor of ``start`` containing ``pyproject.toml``."""
    start = (start or Path.cwd()).resolve()
    for candidate in (start, *start.parents):
        if (candidate / "pyproject.toml").is_file():
            return candidate
    return start


def build_parser() -> argparse.ArgumentParser:
    root = find_project_root()
    parser = argparse.ArgumentParser(
        prog="python -m purchase_patterns.ingestion",
        description="Ingest the Online Retail II workbook into raw Parquet files.",
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=root / DEFAULT_SOURCE,
        help="Path to the source .xlsx workbook (default: %(default)s).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=root / DEFAULT_OUTPUT_DIR,
        help="Directory that will contain the dataset folder (default: %(default)s).",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help="Rows per Arrow batch / Parquet row group (default: %(default)s).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run ingestion and return a process exit code (0 = pass, 1 = fail)."""
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    try:
        result = ingest_workbook(args.source, args.output_dir, batch_size=args.batch_size)
    except IngestionError as exc:
        logger.error("Ingestion failed: %s", exc)
        return 1

    totals = result.validation_report["totals"]
    logger.info(
        "Status %s: %d rows written to %s",
        result.status,
        totals["rows_written"],
        result.output_dir,
    )
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
