-- Barbora Migration: Create Materialized View for Product Ingredient Cards
-- Run this AFTER the alter table migration
-- 
-- This view pre-aggregates ingredient data per product as JSONB for fast API responses.
-- Refresh after daily scraping with: REFRESH MATERIALIZED VIEW CONCURRENTLY product_ingredient_cards;
--
-- NOTE: This version uses Barbora's normalized_categories table structure.
-- If your project uses a different category table name, adjust the JOIN accordingly.

-- Drop existing view if present (for re-running migration)
DROP MATERIALIZED VIEW IF EXISTS product_ingredient_cards;

-- Create materialized view with aggregated ingredient analysis
CREATE MATERIALIZED VIEW product_ingredient_cards AS
SELECT 
    p.sku,
    p.name,
    p.category_id,
    nc.name_lv AS category_name,
    COALESCE(
        jsonb_agg(
            jsonb_build_object(
                'id', ia.id,
                'name', COALESCE(ia.clean_name, ia.ingredient),
                'category', ia.category,
                'is_processed', ia.is_processed,
                'suspicion_level', ia.suspicion_level,
                'suspicion_category', ia.suspicion_category,
                'health_note', ia.health_note
            ) ORDER BY ia.frequency DESC
        ) FILTER (WHERE ia.id IS NOT NULL),
        '[]'::jsonb
    ) AS ingredients,
    COUNT(ia.id) FILTER (WHERE ia.category = 'natural') AS natural_count,
    COUNT(ia.id) FILTER (WHERE ia.category = 'processed') AS processed_count,
    COUNT(ia.id) FILTER (WHERE ia.suspicion_level = 'avoid') AS avoid_count,
    COUNT(ia.id) FILTER (WHERE ia.suspicion_level = 'limit') AS limit_count,
    COUNT(ia.id) FILTER (WHERE ia.suspicion_level = 'caution') AS caution_count
FROM products p
LEFT JOIN normalized_categories nc ON p.category_id = nc.category_id
LEFT JOIN ingredient_product_mapping ipm ON p.sku = ipm.product_sku
LEFT JOIN ingredient_analysis ia ON ipm.ingredient_id = ia.id
GROUP BY p.sku, p.name, p.category_id, nc.name_lv;

-- Create unique index for fast lookups and CONCURRENTLY refresh support
CREATE UNIQUE INDEX idx_product_ingredient_cards_sku ON product_ingredient_cards(sku);

-- Usage:
-- SELECT sku, name, ingredients, natural_count, processed_count, avoid_count
-- FROM product_ingredient_cards
-- WHERE sku = 'YOUR_SKU';
--
-- Each ingredient in the 'ingredients' JSONB array contains:
--   - id: ingredient_analysis.id (stable foreign key)
--   - name: cleaned ingredient name
--   - category: 'natural', 'processed', or 'uncategorized'
--   - is_processed: true/false/null
--   - suspicion_level: 'avoid'/'limit'/'caution'/'clean'/null
--   - suspicion_category: type of concern
--   - health_note: Latvian health warning (max 200 chars)
--
-- Refresh after daily updates:
-- REFRESH MATERIALIZED VIEW CONCURRENTLY product_ingredient_cards;
