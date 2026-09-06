-- Migration 007: allow the two intermediate suspicious-refresh stages.
-- Migration 006 may already be applied, so this must remain a forward migration.

ALTER TABLE product_processing_log
    DROP CONSTRAINT IF EXISTS check_product_status;

ALTER TABLE product_processing_log
    DROP CONSTRAINT IF EXISTS product_processing_log_status_check;

ALTER TABLE product_processing_log
    ADD CONSTRAINT check_product_status
    CHECK (status IN (
        'pending', 'processing', 'scraped', 'validating',
        'completed', 'failed', 'skipped'
    ));