-- Load raw interim line items for the quality stage.
-- Placeholders substituted by the Python orchestrator:
--   {{INTERIM_GLOB}}  e.g. '/path/to/data/interim/online_retail_ii/*.parquet'

CREATE OR REPLACE VIEW raw_line_items AS
SELECT
    invoice,
    stock_code,
    description,
    quantity,
    invoice_date,
    price,
    customer_id,
    country,
    source_sheet,
    source_row_number
FROM read_parquet('{{INTERIM_GLOB}}');
