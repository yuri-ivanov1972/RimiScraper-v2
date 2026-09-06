-- Migration 006: dedicated two-phase refresh jobs for suspicious products.

ALTER TABLE category_processing_jobs
    ALTER COLUMN category_code DROP NOT NULL,
    ADD COLUMN IF NOT EXISTS job_type VARCHAR(30) NOT NULL DEFAULT 'category',
    ADD COLUMN IF NOT EXISTS phase VARCHAR(20) NOT NULL DEFAULT 'queued',
    ADD COLUMN IF NOT EXISTS validation_completed_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS validation_failed_count INTEGER NOT NULL DEFAULT 0;

ALTER TABLE product_processing_log
    ADD COLUMN IF NOT EXISTS product_id INTEGER REFERENCES products (product_id),
    ADD COLUMN IF NOT EXISTS scrape_status VARCHAR(20) NOT NULL DEFAULT 'pending',
    ADD COLUMN IF NOT EXISTS validation_status VARCHAR(20) NOT NULL DEFAULT 'pending';

CREATE UNIQUE INDEX IF NOT EXISTS idx_unique_active_suspicious_refresh
    ON category_processing_jobs (job_type)
    WHERE job_type = 'suspicious_refresh'
      AND status IN ('queued', 'in_progress');

CREATE INDEX IF NOT EXISTS idx_product_log_refresh_status
    ON product_processing_log (job_id, scrape_status, validation_status);