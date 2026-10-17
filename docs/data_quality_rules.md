# Data Quality Rules (`quality_v1`)

Stage: Data Quality & Preparation  
Input: `data/interim/online_retail_ii/*.parquet`  
Output: `data/processed/quality/`  
Command: `uv run python -m purchase_patterns.quality`

This stage **never silently drops** rows. Every interim line item appears in
`transactions_classified.parquet` with flags and `exclusion_codes`. Downstream
customer segmentation and 60-day repeat-purchase modeling should read
`valid_purchases.parquet` only.

Evidence counts below were measured on the current interim extract
(1,067,371 raw rows) unless noted as synthetic.

## Canonical selection (R01)

Business key:

`(invoice, stock_code, description, quantity, invoice_date, price, customer_id, country)`

When multiple rows share a key:

1. Prefer `source_sheet = Year 2010-2011`.
2. Then lowest `source_row_number`.

| Metric | Count |
| --- | ---: |
| Raw rows | 1,067,371 |
| Distinct business keys (canonical) | 1,033,036 |
| Non-canonical exact-duplicate extras | 34,335 |
| Cross-sheet identical groups (Dec 1–9 2010) | 22,202 |

Non-winners get `exclusion_codes` containing `not_canonical`,
`is_exact_duplicate = true`, and remain in the classified table.

## Rule catalog

| ID | Rule | Detection | Exclusion code | Evidence (raw, approx.) |
| --- | --- | --- | --- | ---: |
| R01 | Duplicate / non-canonical | Loser of canonical window | `not_canonical` | 34,335 |
| R02 | Cancellation invoice | `invoice` starts with `C` (UCI) | `cancellation` | 19,494 |
| R03 | Accounting adjustment | `invoice` starts with `A`, or `stock_code=B` with “Adjust” | `accounting_adjustment` | 5 bad-debt rows (+ related) |
| R04 | Non-positive quantity | `quantity <= 0` and not R02 | `non_positive_quantity` | 3,393 after dedupe (non-cancel) |
| R05 | Non-positive price | `price <= 0` | `non_positive_price` | 6,207 (0: 6,202; &lt;0: 5) |
| R06 | Missing customer | `customer_id IS NULL` | `missing_customer_id` | 243,007 (22.8%) |
| R07 | Non-product stock | deny-list / prefixes below | `non_product_stock_code` | ~6k after dedupe |
| R08 | Ambiguous cancellation | `C%` and `quantity >= 0` | `ambiguous_cancellation` | 1 (`C496350`) |
| R09 | Invalid timestamp | null or outside `[2009-12-01, 2011-12-10)` | `invalid_invoice_date` | 0 in current extract |
| R10 | Missing keys | null `invoice` or `stock_code` | `missing_key` | 0 in current extract |

A row may carry **multiple** exclusion codes.  
`is_eligible_valid_purchase` is true only when the row is canonical and has **no**
content-quality exclusions (equivalently: canonical and empty exclusion list
aside from never including `not_canonical` on winners).

## Non-product stock codes (R07)

Exact (case-insensitive):  
`POST`, `DOT`, `M`, `D`, `S`, `B`, `C2`, `CRUK`, `BANK CHARGES`, `PADS`,
`AMAZONFEE`, `ADJUST`, `ADJUST2`.

Prefixes: `GIFT%`, `TEST%`, `DCGS%`.

## Record types

Assigned with priority: `invalid` → `ambiguous` → `accounting_adjustment` →
`cancellation` → `return_or_adjustment` → `non_product` → `purchase`.

## Valid purchases funnel (`quality_v1`)

| Stage | Rows |
| --- | ---: |
| Classified (= raw) | 1,067,371 |
| Canonical | 1,033,036 |
| Valid purchases | 776,579 |
| Distinct customers (valid) | 5,852 |
| Distinct invoices (valid) | 36,594 |

## Known biases and limitations

1. **Missing Customer ID (~23%)** — required exclusion for customer-level ML.
   Anonymous traffic remains in `transactions_classified` for catalog/revenue EDA.
2. **Returns not netted** — cancellations and negative quantities are classified
   but not subtracted from purchase history. A later `net_purchases` view can use
   this audit trail.
3. **Description is part of the business key** — whitespace variants are not
   collapsed (raw preservation).
4. **Deny-list may evolve** — versioned as `rule_version = quality_v1`.

## Reconciliation identities

The run fails (exit 1; previous publish untouched) unless:

```
raw_rows = classified_rows
classified_rows = canonical_rows + non_canonical_rows
canonical_rows = distinct business keys
canonical_rows = valid_rows + excluded_canonical_rows
valid_purchases table row count = valid_rows
valid_purchases has no null CID, non-positive qty/price, C/A invoices, or duplicate keys
```
