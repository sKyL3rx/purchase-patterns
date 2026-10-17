"""Orchestrate DuckDB quality transforms: interim Parquet -> classified + valid."""

from __future__ import annotations

import datetime as dt
import json
import logging
import platform
import shutil
import time
import uuid
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

import duckdb
import pyarrow.parquet as pq

from purchase_patterns.ingestion.pipeline import file_sha256
from purchase_patterns.quality.schema import (
    CLASSIFIED_FILE,
    DATASET_NAME,
    INTERIM_PARQUET_GLOB,
    METADATA_FILE,
    PREFERRED_SHEET,
    QUALITY_REPORT_FILE,
    RECONCILIATION_FILE,
    RULE_VERSION,
    VALID_PURCHASES_FILE,
    QualityError,
)
from purchase_patterns.quality.validation import (
    PASS,
    build_quality_report,
    build_reconciliation_report,
)

logger = logging.getLogger(__name__)

SQL_FILES = ("01_load.sql", "02_classify.sql", "03_publish.sql")


def find_sql_dir(start: Path | None = None) -> Path:
    """Return the ``sql/quality`` directory next to the project ``pyproject.toml``."""
    start = (start or Path(__file__)).resolve()
    for candidate in (start, *start.parents):
        sql_dir = candidate / "sql" / "quality"
        if sql_dir.is_dir() and (candidate / "pyproject.toml").is_file():
            return sql_dir
    raise QualityError("Could not locate sql/quality relative to pyproject.toml")


@dataclass(frozen=True)
class QualityResult:
    """Outcome of a quality-pipeline run."""

    run_id: str
    status: str
    output_dir: Path
    classified_path: Path
    valid_purchases_path: Path
    quality_report_path: Path
    reconciliation_path: Path
    metadata_path: Path
    quality_report: dict[str, Any]
    reconciliation_report: dict[str, Any]

    @property
    def passed(self) -> bool:
        return self.status == PASS


def _package_version(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:
        return "unknown"


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _render_sql(template: str, mapping: dict[str, str]) -> str:
    rendered = template
    for key, value in mapping.items():
        rendered = rendered.replace(f"{{{{{key}}}}}", value)
    return rendered


def _load_sql(name: str, sql_dir: Path | None = None) -> str:
    path = (sql_dir or find_sql_dir()) / name
    if not path.is_file():
        raise QualityError(f"SQL script not found: {path}")
    return path.read_text(encoding="utf-8")


def _list_interim_parquet(interim_dir: Path) -> list[Path]:
    files = sorted(interim_dir.glob(INTERIM_PARQUET_GLOB))
    # Ignore sidecar JSON accidentally matching a broader glob; only .parquet.
    files = [path for path in files if path.suffix.lower() == ".parquet"]
    if not files:
        raise QualityError(f"No Parquet files found in interim directory: {interim_dir}")
    return files


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


def run_quality_pipeline(
    interim_dir: Path,
    output_dir: Path,
    *,
    dataset_name: str = DATASET_NAME,
    rule_version: str = RULE_VERSION,
    preferred_sheet: str = PREFERRED_SHEET,
) -> QualityResult:
    """Classify interim line items and publish quality outputs under ``output_dir``.

    Raises:
        QualityError: if interim inputs are missing. Reconciliation failures do not
            raise; they return ``status="fail"`` and keep outputs under ``.failed-*``.
    """
    interim_dir = Path(interim_dir)
    output_dir = Path(output_dir)
    if not interim_dir.is_dir():
        raise QualityError(f"Interim directory not found: {interim_dir}")

    parquet_files = _list_interim_parquet(interim_dir)
    interim_hashes = {path.name: file_sha256(path) for path in parquet_files}
    interim_glob = (interim_dir / INTERIM_PARQUET_GLOB).as_posix()

    run_id = uuid.uuid4().hex[:12]
    started_at = _utc_now()
    started_clock = time.perf_counter()
    logger.info("Run %s: quality pipeline on %s", run_id, interim_dir)

    target_dir = output_dir / dataset_name
    staging_dir = output_dir / f".staging-{dataset_name}-{run_id}"
    staging_dir.mkdir(parents=True)

    classified_staging = staging_dir / CLASSIFIED_FILE
    valid_staging = staging_dir / VALID_PURCHASES_FILE

    placeholders = {
        "INTERIM_GLOB": interim_glob,
        "RULE_VERSION": rule_version,
        "PREFERRED_SHEET": preferred_sheet,
        "CLASSIFIED_PATH": classified_staging.as_posix(),
        "VALID_PATH": valid_staging.as_posix(),
    }

    sql_dir = find_sql_dir()
    con = duckdb.connect()
    try:
        for sql_name in SQL_FILES:
            sql_text = _render_sql(_load_sql(sql_name, sql_dir), placeholders)
            con.execute(sql_text)

        raw_rows = int(con.execute("SELECT count(*) FROM raw_line_items").fetchone()[0])
        quality_report = build_quality_report(con)
        reconciliation = build_reconciliation_report(
            con, raw_rows=raw_rows, interim_hashes=interim_hashes
        )
        quality_report["status"] = reconciliation["status"]
    except Exception:
        shutil.rmtree(staging_dir, ignore_errors=True)
        con.close()
        raise

    finished_at = _utc_now()
    status = reconciliation["status"]

    metadata = {
        "run_id": run_id,
        "dataset": dataset_name,
        "status": status,
        "rule_version": rule_version,
        "preferred_sheet": preferred_sheet,
        "started_at_utc": started_at.isoformat(),
        "finished_at_utc": finished_at.isoformat(),
        "duration_seconds": round(time.perf_counter() - started_clock, 3),
        "source": {
            "interim_dir": interim_dir.as_posix(),
            "parquet_files": [
                {
                    "file": path.name,
                    "rows": pq.read_metadata(path).num_rows,
                    "size_bytes": path.stat().st_size,
                    "sha256": interim_hashes[path.name],
                }
                for path in parquet_files
            ],
        },
        "environment": {
            "python": platform.python_version(),
            "purchase_patterns": _package_version("purchase-patterns"),
            "duckdb": duckdb.__version__,
        },
        "outputs": {
            "classified": {
                "file": CLASSIFIED_FILE,
                "rows": reconciliation["counts"]["classified_rows"],
                "size_bytes": classified_staging.stat().st_size,
                "sha256": file_sha256(classified_staging),
            },
            "valid_purchases": {
                "file": VALID_PURCHASES_FILE,
                "rows": reconciliation["counts"]["valid_rows"],
                "size_bytes": valid_staging.stat().st_size,
                "sha256": file_sha256(valid_staging),
            },
        },
        "reconciliation_status": status,
    }

    _write_json(staging_dir / QUALITY_REPORT_FILE, quality_report)
    _write_json(staging_dir / RECONCILIATION_FILE, reconciliation)
    _write_json(staging_dir / METADATA_FILE, metadata)
    con.close()

    if status == PASS:
        _publish(staging_dir, target_dir, run_id)
        final_dir = target_dir
        logger.info("Run %s passed reconciliation; published to %s", run_id, final_dir)
    else:
        final_dir = output_dir / f".failed-{dataset_name}-{run_id}"
        staging_dir.rename(final_dir)
        logger.error("Run %s failed reconciliation; outputs kept in %s", run_id, final_dir)

    return QualityResult(
        run_id=run_id,
        status=status,
        output_dir=final_dir,
        classified_path=final_dir / CLASSIFIED_FILE,
        valid_purchases_path=final_dir / VALID_PURCHASES_FILE,
        quality_report_path=final_dir / QUALITY_REPORT_FILE,
        reconciliation_path=final_dir / RECONCILIATION_FILE,
        metadata_path=final_dir / METADATA_FILE,
        quality_report=quality_report,
        reconciliation_report=reconciliation,
    )
