-- Migration 003: Add 'general' to nutriscore_category_type CHECK constraint
-- Applied: 2026-08-21

ALTER TABLE normalized_categories
    DROP CONSTRAINT IF EXISTS normalized_categories_nutriscore_category_type_check,
    ADD CONSTRAINT normalized_categories_nutriscore_category_type_check
        CHECK (nutriscore_category_type IN (
            'general', 'beverage', 'cheese', 'red_meat', 'fat_oil_nut', 'full_fvn', 'half_fvn'
        ));
