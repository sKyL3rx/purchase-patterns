"""Raw ingestion of the Online Retail II workbook into Parquet."""

from purchase_patterns.ingestion.pipeline import IngestionResult, ingest_workbook
from purchase_patterns.ingestion.schema import (
    EXPECTED_SHEETS,
    RAW_SCHEMA,
    SOURCE_HEADER,
    IngestionError,
)

__all__ = [
    "EXPECTED_SHEETS",
    "RAW_SCHEMA",
    "SOURCE_HEADER",
    "IngestionError",
    "IngestionResult",
    "ingest_workbook",
]
