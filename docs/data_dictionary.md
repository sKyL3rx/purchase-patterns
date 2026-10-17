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

## Quality layer: `quality` (`quality_v1`)

Produced by `uv run python -m purchase_patterns.quality` into
`data/processed/quality/` (gitignored). Rules are documented in
[data_quality_rules.md](data_quality_rules.md).

| File | Contents |
| --- | --- |
| `transactions_classified.parquet` | Every interim row + flags, `record_type`, `exclusion_codes`, canonical lineage |
| `valid_purchases.parquet` | Customer-eligible product purchases for segmentation / 60-day prediction |
| `_quality_report.json` | Per-rule counts, record types, top non-product codes, valid-set stats |
| `_reconciliation.json` | Row-count identities and valid-purchase guarantees |
| `_quality_metadata.json` | Run id, rule version, interim SHA-256s, output hashes |

```sql
select * from read_parquet('data/processed/quality/transactions_classified.parquet');
select * from read_parquet('data/processed/quality/valid_purchases.parquet');
```

### `transactions_classified` columns

All raw-layer columns (unmodified), plus:

| Column | Type | Notes |
| --- | --- | --- |
| `business_key_hash` | string | MD5 of the business key |
| `duplicate_group_size` | int32 | Rows sharing the business key |
| `is_canonical` | bool | Winner of R01 (prefer `Year 2010-2011`, then lowest `source_row_number`) |
| `canonical_source_sheet` | string | Sheet of the winning row |
| `canonical_source_row_number` | int32 | Excel row of the winning row |
| `is_cross_sheet_duplicate` | bool | Group spans both worksheets |
| `is_exact_duplicate` | bool | Non-canonical member of a duplicate group |
| `is_cancellation` | bool | Invoice starts with `C` |
| `is_accounting_adjustment` | bool | Invoice starts with `A`, or stock `B` adjust |
| `is_non_positive_quantity` | bool | `quantity <= 0` |
| `is_non_positive_price` | bool | `price <= 0` |
| `is_missing_customer_id` | bool | `customer_id` is null |
| `is_non_product` | bool | Admin / fee / gift / test stock codes |
| `is_ambiguous` | bool | `C` invoice with non-negative quantity |
| `is_invalid_timestamp` | bool | Null or outside the known data window |
| `record_type` | string | `purchase` / `cancellation` / `return_or_adjustment` / `accounting_adjustment` / `non_product` / `ambiguous` / `invalid` |
| `exclusion_codes` | list\<string\> | Ordered rule codes; empty on eligible canonical rows |
| `is_eligible_valid_purchase` | bool | Canonical and no content exclusions |
| `line_amount` | float64 | `quantity * price` (signed) |
| `description_trimmed` | string | Trimmed copy for inspection; original `description` preserved |
| `is_uk` | bool | `country = 'United Kingdom'` |
| `rule_version` | string | e.g. `quality_v1` |

### `valid_purchases` columns

| Column | Type | Notes |
| --- | --- | --- |
| `invoice` | string | Never starts with `C` or `A` |
| `stock_code` | string | Product codes only (R07 excluded) |
| `description` | string | As in source |
| `quantity` | int64 | Always `> 0` |
| `invoice_date` | timestamp[us] | Naive |
| `price` | float64 | Always `> 0` |
| `customer_id` | string | Never null |
| `country` | string | As in source |
| `line_amount` | float64 | `quantity * price` |
| `source_sheet` | string | Canonical source sheet |
| `source_row_number` | int32 | Canonical source row |
| `business_key_hash` | string | Unique in this table |
| `is_uk` | bool | |
| `rule_version` | string | |
