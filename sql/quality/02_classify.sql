-- Classify every raw line item: flags, record_type, canonical pick, exclusion codes.
-- Placeholders: {{RULE_VERSION}}, {{PREFERRED_SHEET}}
--
-- Rule IDs (see docs/data_quality_rules.md):
--   R01 duplicate / canonical selection
--   R02 cancellation (invoice LIKE 'C%')
--   R03 accounting adjustment (invoice LIKE 'A%' or stock B adjust)
--   R04 non-positive quantity (qty <= 0, not a cancellation)
--   R05 non-positive price
--   R06 missing customer_id
--   R07 non-product stock codes
--   R08 ambiguous cancellation (C% with quantity >= 0)
--   R09 invalid invoice_date
--   R10 missing invoice or stock_code

CREATE OR REPLACE TEMP TABLE flagged_line_items AS
SELECT
    r.*,
    md5(
        concat_ws(
            '||',
            coalesce(r.invoice, ''),
            coalesce(r.stock_code, ''),
            coalesce(r.description, ''),
            coalesce(cast(r.quantity AS VARCHAR), ''),
            coalesce(strftime(r.invoice_date, '%Y-%m-%d %H:%M:%S'), ''),
            coalesce(printf('%.15g', r.price), ''),
            coalesce(r.customer_id, ''),
            coalesce(r.country, '')
        )
    ) AS business_key_hash,
    CASE
        WHEN r.source_sheet = '{{PREFERRED_SHEET}}' THEN 0
        ELSE 1
    END AS sheet_priority,
    (r.invoice IS NOT NULL AND starts_with(r.invoice, 'C')) AS is_cancellation,
    (
        (r.invoice IS NOT NULL AND starts_with(r.invoice, 'A'))
        OR (
            upper(coalesce(r.stock_code, '')) = 'B'
            AND lower(coalesce(r.description, '')) LIKE '%adjust%'
        )
    ) AS is_accounting_adjustment,
    (r.quantity IS NOT NULL AND r.quantity <= 0) AS is_non_positive_quantity,
    (r.price IS NOT NULL AND r.price <= 0) AS is_non_positive_price,
    (r.customer_id IS NULL) AS is_missing_customer_id,
    (
        upper(coalesce(r.stock_code, '')) IN (
            'POST', 'DOT', 'M', 'D', 'S', 'B', 'C2', 'CRUK',
            'BANK CHARGES', 'PADS', 'AMAZONFEE', 'ADJUST', 'ADJUST2'
        )
        OR starts_with(upper(coalesce(r.stock_code, '')), 'GIFT')
        OR starts_with(upper(coalesce(r.stock_code, '')), 'TEST')
        OR starts_with(upper(coalesce(r.stock_code, '')), 'DCGS')
    ) AS is_non_product,
    (
        r.invoice IS NOT NULL
        AND starts_with(r.invoice, 'C')
        AND r.quantity IS NOT NULL
        AND r.quantity >= 0
    ) AS is_ambiguous,
    (
        r.invoice_date IS NULL
        OR r.invoice_date < TIMESTAMP '2009-12-01'
        OR r.invoice_date >= TIMESTAMP '2011-12-10'
    ) AS is_invalid_timestamp,
    (r.invoice IS NULL OR r.stock_code IS NULL) AS is_missing_key,
    trim(r.description) AS description_trimmed,
    (r.country = 'United Kingdom') AS is_uk,
    CASE
        WHEN r.quantity IS NOT NULL AND r.price IS NOT NULL
            THEN r.quantity * r.price
        ELSE NULL
    END AS line_amount,
    '{{RULE_VERSION}}' AS rule_version
FROM raw_line_items AS r;

CREATE OR REPLACE TEMP TABLE ranked_line_items AS
SELECT
    f.*,
    cast(count(*) OVER (PARTITION BY f.business_key_hash) AS INTEGER) AS duplicate_group_size,
    row_number() OVER (
        PARTITION BY f.business_key_hash
        ORDER BY f.sheet_priority ASC, f.source_row_number ASC
    ) AS rn,
    (
        count(DISTINCT f.source_sheet) OVER (PARTITION BY f.business_key_hash) > 1
    ) AS is_cross_sheet_duplicate
FROM flagged_line_items AS f;

CREATE OR REPLACE TEMP TABLE canonical_keys AS
SELECT
    business_key_hash,
    source_sheet AS canonical_source_sheet,
    cast(source_row_number AS INTEGER) AS canonical_source_row_number
FROM ranked_line_items
WHERE rn = 1;

CREATE OR REPLACE TEMP TABLE classified_line_items AS
SELECT
    r.invoice,
    r.stock_code,
    r.description,
    r.quantity,
    r.invoice_date,
    r.price,
    r.customer_id,
    r.country,
    r.source_sheet,
    r.source_row_number,
    r.business_key_hash,
    r.duplicate_group_size,
    (r.rn = 1) AS is_canonical,
    c.canonical_source_sheet,
    c.canonical_source_row_number,
    r.is_cross_sheet_duplicate,
    (r.duplicate_group_size > 1 AND r.rn <> 1) AS is_exact_duplicate,
    r.is_cancellation,
    r.is_accounting_adjustment,
    r.is_non_positive_quantity,
    r.is_non_positive_price,
    r.is_missing_customer_id,
    r.is_non_product,
    r.is_ambiguous,
    r.is_invalid_timestamp,
    CASE
        WHEN r.is_missing_key OR r.is_invalid_timestamp THEN 'invalid'
        WHEN r.is_ambiguous THEN 'ambiguous'
        WHEN r.is_accounting_adjustment THEN 'accounting_adjustment'
        WHEN r.is_cancellation THEN 'cancellation'
        WHEN r.is_non_positive_quantity AND NOT r.is_cancellation THEN 'return_or_adjustment'
        WHEN r.is_non_product THEN 'non_product'
        ELSE 'purchase'
    END AS record_type,
    list_filter(
        [
            CASE WHEN r.rn <> 1 THEN 'not_canonical' END,
            CASE WHEN r.is_cancellation THEN 'cancellation' END,
            CASE WHEN r.is_accounting_adjustment THEN 'accounting_adjustment' END,
            CASE
                WHEN r.is_non_positive_quantity AND NOT r.is_cancellation
                    THEN 'non_positive_quantity'
            END,
            CASE WHEN r.is_non_positive_price THEN 'non_positive_price' END,
            CASE WHEN r.is_missing_customer_id THEN 'missing_customer_id' END,
            CASE WHEN r.is_non_product THEN 'non_product_stock_code' END,
            CASE WHEN r.is_ambiguous THEN 'ambiguous_cancellation' END,
            CASE WHEN r.is_invalid_timestamp THEN 'invalid_invoice_date' END,
            CASE WHEN r.is_missing_key THEN 'missing_key' END
        ],
        x -> x IS NOT NULL
    ) AS exclusion_codes,
    (
        r.rn = 1
        AND NOT r.is_cancellation
        AND NOT r.is_accounting_adjustment
        AND NOT (r.is_non_positive_quantity AND NOT r.is_cancellation)
        AND NOT r.is_non_positive_price
        AND NOT r.is_missing_customer_id
        AND NOT r.is_non_product
        AND NOT r.is_ambiguous
        AND NOT r.is_invalid_timestamp
        AND NOT r.is_missing_key
    ) AS is_eligible_valid_purchase,
    r.line_amount,
    r.description_trimmed,
    r.is_uk,
    r.rule_version
FROM ranked_line_items AS r
INNER JOIN canonical_keys AS c
    ON r.business_key_hash = c.business_key_hash;

CREATE OR REPLACE TEMP TABLE valid_purchases AS
SELECT
    invoice,
    stock_code,
    description,
    quantity,
    invoice_date,
    price,
    customer_id,
    country,
    line_amount,
    source_sheet,
    source_row_number,
    business_key_hash,
    is_uk,
    rule_version
FROM classified_line_items
WHERE is_eligible_valid_purchase;
