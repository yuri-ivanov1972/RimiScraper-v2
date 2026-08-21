-- Migration 002: Add Nutri-Score category type columns to normalized_categories
-- Applied: 2026-08-21

ALTER TABLE normalized_categories
    ADD COLUMN IF NOT EXISTS nutriscore_category_type TEXT
        CHECK (nutriscore_category_type IN (
            'beverage', 'cheese', 'red_meat', 'fat_oil_nut', 'full_fvn', 'half_fvn'
        )),
    ADD COLUMN IF NOT EXISTS nutriscore_category_type_explicit BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS idx_normalized_categories_ns_type
    ON normalized_categories (nutriscore_category_type);
