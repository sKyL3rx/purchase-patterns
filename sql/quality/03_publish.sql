-- Publish classified and valid-purchase tables to staging Parquet paths.
-- Placeholders: {{CLASSIFIED_PATH}}, {{VALID_PATH}}

COPY classified_line_items
TO '{{CLASSIFIED_PATH}}'
(FORMAT PARQUET, COMPRESSION ZSTD);

COPY valid_purchases
TO '{{VALID_PATH}}'
(FORMAT PARQUET, COMPRESSION ZSTD);
