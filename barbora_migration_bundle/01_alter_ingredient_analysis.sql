-- Barbora Migration: Add AI Categorization + NOVA4 Suspicion Fields to ingredient_analysis
-- Run this FIRST before deploying the analyzer code
-- 
-- This migration adds the fields needed for AI-powered ingredient categorization
-- and NOVA4 ultra-processed food marker detection.

-- Add AI categorization columns
ALTER TABLE ingredient_analysis 
ADD COLUMN IF NOT EXISTS clean_name TEXT,
ADD COLUMN IF NOT EXISTS category VARCHAR(20) DEFAULT 'uncategorized',
ADD COLUMN IF NOT EXISTS is_processed BOOLEAN;

-- Add NOVA4 suspicion analysis columns
ALTER TABLE ingredient_analysis 
ADD COLUMN IF NOT EXISTS suspicion_level TEXT,
ADD COLUMN IF NOT EXISTS suspicion_category TEXT,
ADD COLUMN IF NOT EXISTS health_note TEXT;

-- Add performance indexes
CREATE INDEX IF NOT EXISTS idx_ingredient_analysis_category ON ingredient_analysis(category);
CREATE INDEX IF NOT EXISTS idx_ingredient_analysis_suspicion ON ingredient_analysis(suspicion_level);
CREATE INDEX IF NOT EXISTS idx_ingredient_analysis_processed ON ingredient_analysis(is_processed);
CREATE INDEX IF NOT EXISTS idx_ingredient_product_mapping_sku ON ingredient_product_mapping(product_sku);

-- Column descriptions:
-- clean_name: AI-cleaned ingredient name (removes parentheses, asterisks, percentages)
-- category: 'natural', 'processed', or 'uncategorized'
-- is_processed: TRUE=processed, FALSE=natural, NULL=uncategorized
-- suspicion_level: 'avoid', 'limit', 'caution', 'clean', or NULL (NULL for natural ingredients)
-- suspicion_category: 'sweetener', 'emulsifier', 'dye', 'flavor_enhancer', 'preservative', 'filler', 'processing_aid', 'industrial_fat'
-- health_note: Brief health concern in Latvian (max 200 chars)

COMMENT ON COLUMN ingredient_analysis.clean_name IS 'AI-cleaned ingredient name';
COMMENT ON COLUMN ingredient_analysis.category IS 'natural/processed/uncategorized';
COMMENT ON COLUMN ingredient_analysis.is_processed IS 'TRUE=processed, FALSE=natural, NULL=uncategorized';
COMMENT ON COLUMN ingredient_analysis.suspicion_level IS 'avoid/limit/caution/clean/NULL (NULL for natural)';
COMMENT ON COLUMN ingredient_analysis.suspicion_category IS 'Type of additive concern';
COMMENT ON COLUMN ingredient_analysis.health_note IS 'Health warning in Latvian (max 200 chars)';
