# purchase-patterns

## Ingest raw data

Place the source workbook at `data/raw/online_retail_II.xlsx` (not committed), then run:

```bash
uv run python -m purchase_patterns.ingestion
```

This streams both worksheets into Parquet under `data/interim/online_retail_ii/`, together with
`_ingestion_metadata.json` and `_validation_report.json`. The command exits non-zero if the
source violates the expected contract or validation fails; the previously published output is
left untouched. Options: `--source`, `--output-dir`, `--batch-size`.

The raw-layer schema is documented in [docs/data_dictionary.md](docs/data_dictionary.md).

## Tests

```bash
uv run pytest                  # unit tests on synthetic Excel fixtures
uv run pytest -m integration   # end-to-end run on the real workbook (if present)
```
