-- Migration 001: Add NOVA score columns to normalized_categories
-- Applied: 2026-06-18

ALTER TABLE normalized_categories
    ADD COLUMN IF NOT EXISTS nova_score          INTEGER CHECK (nova_score BETWEEN 1 AND 4),
    ADD COLUMN IF NOT EXISTS nova_score_explicit BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS idx_normalized_categories_nova
    ON normalized_categories (nova_score);
