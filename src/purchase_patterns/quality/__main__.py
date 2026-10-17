"""Command-line entry point: ``uv run python -m purchase_patterns.quality``."""

from __future__ import annotations

import argparse
import logging
from collections.abc import Sequence
from pathlib import Path

from purchase_patterns.quality.pipeline import run_quality_pipeline
from purchase_patterns.quality.schema import QualityError

logger = logging.getLogger("purchase_patterns.quality")

DEFAULT_INTERIM_DIR = Path("data/interim/online_retail_ii")
DEFAULT_OUTPUT_DIR = Path("data/processed")


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
        prog="python -m purchase_patterns.quality",
        description=(
            "Classify interim Online Retail II Parquet into audit-preserving "
            "transactions and valid purchases."
        ),
    )
    parser.add_argument(
        "--interim-dir",
        type=Path,
        default=root / DEFAULT_INTERIM_DIR,
        help="Directory with interim Parquet files (default: %(default)s).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=root / DEFAULT_OUTPUT_DIR,
        help="Parent directory for the quality dataset folder (default: %(default)s).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the quality pipeline and return a process exit code (0 = pass, 1 = fail)."""
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    try:
        result = run_quality_pipeline(args.interim_dir, args.output_dir)
    except QualityError as exc:
        logger.error("Quality pipeline failed: %s", exc)
        return 1

    counts = result.reconciliation_report["counts"]
    logger.info(
        "Status %s: classified=%d valid=%d -> %s",
        result.status,
        counts["classified_rows"],
        counts["valid_rows"],
        result.output_dir,
    )
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
