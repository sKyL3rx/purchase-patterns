# Data Dictionary

## Raw layer: `online_retail_ii`

Source: `data/raw/online_retail_II.xlsx` (UCI Online Retail II, via Kaggle), worksheets
`Year 2009-2010` and `Year 2010-2011`.

Produced by `uv run python -m purchase_patterns.ingestion` into
`data/interim/online_retail_ii/` (gitignored):

| File | Contents |
| --- | --- |
| `year_2009_2010.parquet` | All non-blank rows of `Year 2009-2010` |
| `year_2010_2011.parquet` | All non-blank rows of `Year 2010-2011` |
| `_ingestion_metadata.json` | Run id, timings, source size and SHA-256, library versions, per-file rows/size/SHA-256, schema |
| `_validation_report.json` | Header, row-count, schema and sheet-dimension checks; per-column null counts; `invoice_date` range |

Query both sheets together with DuckDB:

```sql
select * from read_parquet('data/interim/online_retail_ii/*.parquet');
```

### Columns

| Column | Source header | Type | Nullable | Notes |
| --- | --- | --- | --- | --- |
| `invoice` | `Invoice` | string | yes | Invoice number. Numeric cells are rendered without decimals; a leading `C` marks a cancellation and is preserved. |
| `stock_code` | `StockCode` | string | yes | Product code. Mixed numeric/alphanumeric in the source; always stored as text. |
| `description` | `Description` | string | yes | Product name, verbatim (leading/trailing whitespace is kept). |
| `quantity` | `Quantity` | int64 | yes | Units per line. Negative values (returns/adjustments) are kept. |
| `invoice_date` | `InvoiceDate` | timestamp[us] | yes | Invoice date and time, naive (no timezone in the source). |
| `price` | `Price` | float64 | yes | Unit price in GBP as stored in Excel. Zero and negative values are kept. |
| `customer_id` | `Customer ID` | string | yes | Customer identifier. Excel numbers are rendered as integers (`13085`, never `13085.0`); missing values are null, never `"nan"`. |
| `country` | `Country` | string | yes | Customer country, verbatim. |
| `source_sheet` | — | string | no | Worksheet the row came from. |
| `source_row_number` | — | int32 | no | 1-based Excel row number in `source_sheet` (first data row is 2). |

### Ingestion rules

- Values are preserved as-is: no deduplication, trimming, imputation or filtering of
  cancellations, returns, zero prices or missing customers. These belong to the cleaning step.
- Only fully blank rows are skipped; their count is reported per sheet.
- Any cell that cannot be converted to its declared type (for example text in `Quantity` or a
  fractional `Customer ID`) aborts the run with the sheet, row and column; nothing is published.
- The two worksheets overlap in time around December 2010. Overlapping rows are kept in both
  files; see each sheet's `invoice_date_min`/`invoice_date_max` in the validation report.
