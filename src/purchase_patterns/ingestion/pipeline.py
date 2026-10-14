"""Orchestrate raw ingestion: Excel worksheets -> per-sheet Parquet + reports.

Outputs are written to a staging directory next to the target and only
replace the previously published dataset once validation passes, so a failed
run never leaves a partially written dataset in place.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import platform
import shutil
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from purchase_patterns.ingestion.reader import (
    DEFAULT_BATCH_SIZE,
    SheetStats,
    iter_sheet_batches,
    list_sheet_names,
)
from purchase_patterns.ingestion.schema import (
    DATASET_NAME,
    EXPECTED_SHEETS,
    RAW_SCHEMA,
    IngestionError,
    sheet_slug,
)
from purchase_patterns.ingestion.validation import (
    PASS,
    SheetOutput,
    build_validation_report,
)

logger = logging.getLogger(__name__)

PARQUET_COMPRESSION = "zstd"
METADATA_FILE = "_ingestion_metadata.json"
VALIDATION_REPORT_FILE = "_validation_report.json"
_HASH_CHUNK_BYTES = 1024 * 1024


@dataclass(frozen=True)
class IngestionResult:
    """Outcome of an ingestion run.

    ``output_dir`` is the published dataset directory when ``status`` is
    ``"pass"``, or the retained ``.failed-*`` directory otherwise.
    """

    run_id: str
    status: str
    output_dir: Path
    parquet_files: dict[str, Path]
    metadata_path: Path
    validation_report_path: Path
    validation_report: dict[str, Any]

    @property
    def passed(self) -> bool:
        return self.status == PASS


def file_sha256(path: Path) -> str:
    """Return the hex SHA-256 digest of ``path``, read in fixed-size chunks."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_HASH_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def _package_version(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:
        return "unknown"


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _schema_description(schema: pa.Schema) -> list[dict[str, Any]]:
    return [
        {"name": field.name, "type": str(field.type), "nullable": field.nullable}
        for field in schema
    ]


def _write_sheet(source: Path, sheet_name: str, destination: Path, batch_size: int) -> SheetOutput:
    stats = SheetStats(sheet_name=sheet_name)
    rows_written = 0
    with pq.ParquetWriter(destination, RAW_SCHEMA, compression=PARQUET_COMPRESSION) as writer:
        for batch in iter_sheet_batches(source, sheet_name, batch_size=batch_size, stats=stats):
            writer.write_batch(batch)
            rows_written += batch.num_rows
    return SheetOutput(stats=stats, parquet_path=destination, rows_written=rows_written)


def _publish(staging_dir: Path, target_dir: Path, run_id: str) -> None:
    previous_dir = target_dir.with_name(f".previous-{target_dir.name}-{run_id}")
    if target_dir.exists():
        target_dir.rename(previous_dir)
    try:
        staging_dir.rename(target_dir)
    except OSError:
        if previous_dir.exists():
            previous_dir.rename(target_dir)
        raise
    if previous_dir.exists():
        shutil.rmtree(previous_dir)


def ingest_workbook(
    source: Path,
    output_dir: Path,
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
    sheets: Sequence[str] = EXPECTED_SHEETS,
    dataset_name: str = DATASET_NAME,
) -> IngestionResult:
    """Ingest every expected worksheet of ``source`` into ``output_dir/dataset_name``.

    Each worksheet becomes one Parquet file (``RAW_SCHEMA``) alongside
    ``_ingestion_metadata.json`` and ``_validation_report.json``. Values are
    preserved as-is; no business cleaning is applied.

    Raises:
        IngestionError: if the source is missing or violates the source contract.
            Nothing is published and the previous output is left untouched.
    """
    source = Path(source)
    output_dir = Path(output_dir)
    if not source.is_file():
        raise IngestionError(f"Source workbook not found: {source}")

    run_id = uuid.uuid4().hex[:12]
    started_at = _utc_now()
    started_clock = time.perf_counter()
    logger.info("Run %s: ingesting %s", run_id, source)

    available_sheets = list_sheet_names(source)
    missing_sheets = [name for name in sheets if name not in available_sheets]
    if missing_sheets:
        raise IngestionError(
            f"Missing expected sheets {missing_sheets} in {source.name}; "
            f"available sheets: {available_sheets}"
        )
    ignored_sheets = [name for name in available_sheets if name not in sheets]
    if ignored_sheets:
        logger.warning("Ignoring unexpected sheets: %s", ignored_sheets)

    target_dir = output_dir / dataset_name
    staging_dir = output_dir / f".staging-{dataset_name}-{run_id}"
    staging_dir.mkdir(parents=True)

    try:
        outputs = [
            _write_sheet(
                source, sheet_name, staging_dir / f"{sheet_slug(sheet_name)}.parquet", batch_size
            )
            for sheet_name in sheets
        ]
        report = build_validation_report(outputs, expected_sheets=sheets)
        finished_at = _utc_now()

        metadata = {
            "run_id": run_id,
            "dataset": dataset_name,
            "status": report["status"],
            "started_at_utc": started_at.isoformat(),
            "finished_at_utc": finished_at.isoformat(),
            "duration_seconds": round(time.perf_counter() - started_clock, 3),
            "source": {
                "path": source.as_posix(),
                "file_name": source.name,
                "size_bytes": source.stat().st_size,
                "sha256": file_sha256(source),
                "sheets_available": available_sheets,
                "sheets_ignored": ignored_sheets,
            },
            "parameters": {
                "batch_size": batch_size,
                "sheets": list(sheets),
                "compression": PARQUET_COMPRESSION,
            },
            "environment": {
                "python": platform.python_version(),
                "purchase_patterns": _package_version("purchase-patterns"),
                "openpyxl": _package_version("openpyxl"),
                "pyarrow": pa.__version__,
            },
            "outputs": [
                {
                    "sheet_name": output.stats.sheet_name,
                    "file": output.parquet_path.name,
                    "rows": output.rows_written,
                    "size_bytes": output.parquet_path.stat().st_size,
                    "sha256": file_sha256(output.parquet_path),
                }
                for output in outputs
            ],
            "schema": _schema_description(RAW_SCHEMA),
        }
        _write_json(staging_dir / VALIDATION_REPORT_FILE, report)
        _write_json(staging_dir / METADATA_FILE, metadata)
    except BaseException:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise

    if report["status"] == PASS:
        _publish(staging_dir, target_dir, run_id)
        final_dir = target_dir
        logger.info("Run %s passed validation; published to %s", run_id, final_dir)
    else:
        final_dir = output_dir / f".failed-{dataset_name}-{run_id}"
        staging_dir.rename(final_dir)
        logger.error("Run %s failed validation; outputs kept in %s", run_id, final_dir)

    return IngestionResult(
        run_id=run_id,
        status=report["status"],
        output_dir=final_dir,
        parquet_files={
            output.stats.sheet_name: final_dir / output.parquet_path.name for output in outputs
        },
        metadata_path=final_dir / METADATA_FILE,
        validation_report_path=final_dir / VALIDATION_REPORT_FILE,
        validation_report=report,
    )
