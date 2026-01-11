-- ============================================================================
-- RIMI PRODUCT SCRAPER - COMPLETE DATABASE SCHEMA
-- Generated from production database
-- Compatible with PostgreSQL 14+
-- ============================================================================

-- Required extensions
CREATE EXTENSION IF NOT EXISTS pg_trgm;  -- For fuzzy text search on product names

-- ============================================================================
-- CORE TABLES
-- ============================================================================

-- Categories hierarchy (Level 1 = main categories, Level 2/3 = subcategories)
CREATE TABLE normalized_categories (
    category_id SERIAL PRIMARY KEY,
    rimi_category_code TEXT UNIQUE,          -- e.g., "SH-1-1" for Rimi, change for Barbora
    name_lv TEXT NOT NULL,                   -- Latvian name
    name_en TEXT,                            -- English name (optional)
    parent_category_id INTEGER REFERENCES normalized_categories(category_id),
    level INTEGER NOT NULL                   -- 1=main, 2=sub, 3=sub-sub
);

-- Products master table (NO price/availability - those go in price_history)
CREATE TABLE products (
    product_id SERIAL PRIMARY KEY,
    sku TEXT NOT NULL UNIQUE,                -- Product SKU from store
    name TEXT NOT NULL,                      -- Product name
    name_norm TEXT,                          -- Normalized name for search
    rimi_url TEXT UNIQUE,                    -- Full URL (rename to barbora_url for Barbora)
    category_id INTEGER NOT NULL,            -- FK to normalized_categories
    quantity_value NUMERIC(10,2),            -- e.g., 500 (grams)
    quantity_unit VARCHAR(50),               -- e.g., "g", "ml", "kg"
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    country_of_origin VARCHAR(255) DEFAULT 'Unknown',
    nutrition_source VARCHAR(50),            -- 'rimi_scraped', 'ai_generated', 'manual_entry'
    needs_enrichment BOOLEAN DEFAULT FALSE,  -- Flag for AI nutrition enrichment
    enrichment_reviewed BOOLEAN DEFAULT FALSE,
    enrichment_skipped BOOLEAN DEFAULT FALSE
);

-- Price history - ALL price/availability data goes here (append-only)
CREATE TABLE product_price_history (
    price_history_id SERIAL PRIMARY KEY,
    product_id INTEGER NOT NULL REFERENCES products(product_id),
    price NUMERIC(10,2) NOT NULL,            -- Regular price
    currency VARCHAR(3) NOT NULL DEFAULT 'EUR',
    is_available BOOLEAN NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL,
    data_source VARCHAR(100),                -- 'rimi_scraper', 'lightweight_update', etc.
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    price_per_unit NUMERIC(10,2),            -- e.g., 4.02 (€/kg)
    price_per_unit_type VARCHAR(20),         -- e.g., "kg", "l"
    discount_price NUMERIC(10,2),            -- MansRimi/PALDIES loyalty card price
    discount_price_per_unit NUMERIC(10,2)
);

-- Nutrition facts (one row per product)
CREATE TABLE nutritionfacts (
    nutrition_id SERIAL PRIMARY KEY,
    product_id INTEGER NOT NULL UNIQUE REFERENCES products(product_id),
    ingredients_text TEXT,                   -- Raw ingredients string
    energy_kcal INTEGER,
    energy_kj INTEGER,
    fat_total NUMERIC(10,2),
    fat_saturated NUMERIC(10,2),
    carbs_total NUMERIC(10,2),
    carbs_sugars NUMERIC(10,2),
    protein NUMERIC(10,2),
    salt NUMERIC(10,2),
    fiber NUMERIC(10,2),
    nutri_score_grade CHAR(1),               -- A, B, C, D, E
    nutri_score_points INTEGER,              -- Raw score
    data_source_date TIMESTAMPTZ,
    usda_fdc_id INTEGER                      -- Optional USDA FoodData Central ID
);

-- Product photos
CREATE TABLE productphotos (
    photo_id SERIAL PRIMARY KEY,
    product_id INTEGER NOT NULL REFERENCES products(product_id),
    photo_url TEXT NOT NULL,
    alt_text TEXT,
    is_primary BOOLEAN DEFAULT FALSE
);

-- ============================================================================
-- INGREDIENT ANALYSIS TABLES
-- ============================================================================

-- Unique ingredients catalog with frequency tracking, AI categorization, and NOVA4 suspicion analysis
CREATE TABLE ingredient_analysis (
    id SERIAL PRIMARY KEY,
    ingredient TEXT NOT NULL UNIQUE,         -- Normalized ingredient name (lowercase)
    frequency INTEGER NOT NULL DEFAULT 1,    -- How many products contain this
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    clean_name TEXT,                         -- Cleaned name (no parentheses, asterisks, etc.)
    category VARCHAR(20) DEFAULT 'uncategorized',  -- 'natural', 'processed', 'uncategorized'
    is_processed BOOLEAN,                    -- TRUE=processed, FALSE=natural, NULL=uncategorized
    -- NOVA4 suspicion analysis fields (added January 2026)
    suspicion_level TEXT,                    -- 'avoid', 'limit', 'caution', 'clean', NULL (NULL for natural)
    suspicion_category TEXT,                 -- 'sweetener', 'emulsifier', 'dye', 'flavor_enhancer', 
                                            -- 'preservative', 'filler', 'processing_aid', 'industrial_fat'
    health_note TEXT                         -- Brief health concern in Latvian (max 200 chars)
);

-- Many-to-many: products <-> ingredients
CREATE TABLE ingredient_product_mapping (
    ingredient_id INTEGER NOT NULL REFERENCES ingredient_analysis(id),
    product_sku TEXT NOT NULL REFERENCES products(sku),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (ingredient_id, product_sku)
);

-- ============================================================================
-- JOB QUEUE & WORKER TABLES
-- ============================================================================

-- Category processing jobs (job queue)
CREATE TABLE category_processing_jobs (
    id SERIAL PRIMARY KEY,
    category_code VARCHAR(50) NOT NULL,
    category_id INTEGER,
    total_products INTEGER NOT NULL,
    processed_count INTEGER DEFAULT 0,
    status VARCHAR(20) NOT NULL DEFAULT 'in_progress',  -- queued, in_progress, completed, failed
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    priority INTEGER DEFAULT 5,              -- Higher = more urgent
    scheduled_for TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    current_worker_id VARCHAR(100),
    last_heartbeat TIMESTAMP,
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,
    lock_version INTEGER DEFAULT 0,          -- Optimistic locking
    log_path TEXT,
    notes TEXT,
    requested_by VARCHAR(100) DEFAULT 'streamlit_ui',
    update_mode VARCHAR(20) NOT NULL DEFAULT 'full'  -- 'full' or 'incremental'
);

-- Worker registration and heartbeat
CREATE TABLE processing_workers (
    id SERIAL PRIMARY KEY,
    worker_id VARCHAR(100) NOT NULL UNIQUE,
    hostname VARCHAR(255),
    pid INTEGER,
    status VARCHAR(20) NOT NULL DEFAULT 'idle',  -- idle, processing, stopped
    current_job_id INTEGER REFERENCES category_processing_jobs(id),
    last_heartbeat TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    stopped_at TIMESTAMP,
    error_message TEXT
);

-- Job lifecycle events (for debugging)
CREATE TABLE job_events (
    id SERIAL PRIMARY KEY,
    job_id INTEGER NOT NULL REFERENCES category_processing_jobs(id),
    event_type VARCHAR(50) NOT NULL,         -- created, started, progress, completed, failed
    message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    metadata JSONB
);

-- Per-product processing log within a job
CREATE TABLE product_processing_log (
    id SERIAL PRIMARY KEY,
    job_id INTEGER NOT NULL REFERENCES category_processing_jobs(id),
    sku VARCHAR(50) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',  -- pending, success, failed, skipped
    error_message TEXT,
    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================================
-- STATISTICS & LOGGING TABLES
-- ============================================================================

-- Daily update summary logs
CREATE TABLE daily_update_logs (
    id SERIAL PRIMARY KEY,
    update_type VARCHAR(50) NOT NULL DEFAULT 'daily',
    start_time TIMESTAMP NOT NULL,
    end_time TIMESTAMP NOT NULL,
    duration_minutes NUMERIC(10,2),
    categories_processed INTEGER DEFAULT 0,
    jobs_completed INTEGER DEFAULT 0,
    jobs_failed INTEGER DEFAULT 0,
    products_added INTEGER DEFAULT 0,
    products_updated INTEGER DEFAULT 0,
    products_removed INTEGER DEFAULT 0,
    price_changes_count INTEGER DEFAULT 0,
    availability_changes JSONB,              -- Detailed availability breakdown
    ingredient_changes_count INTEGER DEFAULT 0,
    nutrition_changes_count INTEGER DEFAULT 0,
    photo_changes_count INTEGER DEFAULT 0,
    errors_count INTEGER DEFAULT 0,
    error_details JSONB,
    summary TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Per-job update statistics
CREATE TABLE update_statistics (
    id SERIAL PRIMARY KEY,
    job_id INTEGER NOT NULL REFERENCES category_processing_jobs(id),
    category_code VARCHAR(50) NOT NULL,
    total_checked INTEGER DEFAULT 0,
    new_products INTEGER DEFAULT 0,
    price_changed INTEGER DEFAULT 0,
    availability_changed INTEGER DEFAULT 0,
    data_updated INTEGER DEFAULT 0,
    unchanged INTEGER DEFAULT 0,
    failed INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================================
-- INDEXES FOR PERFORMANCE
-- ============================================================================

-- Products indexes
CREATE INDEX idx_products_category_id ON products(category_id);
CREATE INDEX idx_products_sku ON products(sku);
CREATE INDEX idx_products_name ON products USING gin(name gin_trgm_ops);  -- Fuzzy search

-- Price history indexes (critical for performance)
CREATE INDEX idx_price_history_product_id ON product_price_history(product_id);
CREATE INDEX idx_price_history_recorded_at ON product_price_history(recorded_at);
CREATE INDEX idx_price_history_product_recorded ON product_price_history(product_id, recorded_at);
CREATE INDEX idx_price_history_availability ON product_price_history(is_available);
CREATE INDEX idx_price_history_data_source ON product_price_history(data_source);

-- Nutrition indexes
CREATE INDEX idx_nutrition_product_id ON nutritionfacts(product_id);
CREATE INDEX idx_nutrition_nutri_score ON nutritionfacts(nutri_score_grade);
CREATE INDEX idx_nutrition_protein ON nutritionfacts(protein);
CREATE INDEX idx_nutrition_carbs_sugars ON nutritionfacts(carbs_sugars);

-- Photos index
CREATE INDEX idx_photos_product_id ON productphotos(product_id);

-- Ingredient indexes
CREATE INDEX idx_ingredient_analysis_freq ON ingredient_analysis(frequency DESC);
CREATE INDEX idx_ingredient_analysis_category ON ingredient_analysis(category);
CREATE INDEX idx_ingredient_analysis_suspicion ON ingredient_analysis(suspicion_level);
CREATE INDEX idx_ingredient_analysis_processed ON ingredient_analysis(is_processed);
CREATE INDEX idx_ingredient_product_mapping_ingredient ON ingredient_product_mapping(ingredient_id);
CREATE INDEX idx_ingredient_product_mapping_sku ON ingredient_product_mapping(product_sku);

-- Job queue indexes (critical for worker polling)
CREATE INDEX idx_category_jobs_status ON category_processing_jobs(status);
CREATE INDEX idx_category_jobs_code ON category_processing_jobs(category_code);
CREATE INDEX idx_jobs_queue_poll ON category_processing_jobs(status, priority DESC, scheduled_for)
    WHERE status IN ('queued', 'in_progress');
CREATE UNIQUE INDEX idx_unique_active_category ON category_processing_jobs(category_code)
    WHERE status IN ('queued', 'in_progress');  -- Prevent duplicate active jobs

-- Worker indexes
CREATE INDEX idx_workers_status ON processing_workers(status, last_heartbeat DESC);
CREATE INDEX idx_workers_current_job ON processing_workers(current_job_id) WHERE current_job_id IS NOT NULL;

-- Job events indexes
CREATE INDEX idx_job_events_job ON job_events(job_id, created_at DESC);
CREATE INDEX idx_job_events_type ON job_events(event_type, created_at DESC);

-- Product processing log indexes
CREATE INDEX idx_product_log_job ON product_processing_log(job_id);
CREATE INDEX idx_product_log_status ON product_processing_log(job_id, status);
CREATE INDEX idx_product_log_sku ON product_processing_log(sku);

-- Daily update logs indexes
CREATE INDEX idx_daily_update_logs_created_at ON daily_update_logs(created_at DESC);
CREATE INDEX idx_daily_update_logs_start_time ON daily_update_logs(start_time DESC);
CREATE INDEX idx_daily_update_logs_update_type ON daily_update_logs(update_type);

-- Update statistics indexes
CREATE INDEX idx_update_statistics_job_id ON update_statistics(job_id);
CREATE INDEX idx_update_statistics_category_code ON update_statistics(category_code);

-- ============================================================================
-- MATERIALIZED VIEWS FOR DATA SHARING
-- ============================================================================

-- Product cards view with aggregated ingredient analysis (for external project integration)
-- Refresh after nightly scraping: REFRESH MATERIALIZED VIEW CONCURRENTLY product_ingredient_cards;
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

-- Index for fast lookups by SKU
CREATE UNIQUE INDEX idx_product_ingredient_cards_sku ON product_ingredient_cards(sku);

-- ============================================================================
-- USAGE NOTES FOR BARBORA ADAPTATION
-- ============================================================================
-- 1. Rename 'rimi_url' to 'barbora_url' in products table
-- 2. Rename 'rimi_category_code' to 'barbora_category_code' in normalized_categories
-- 3. Update data_source values: 'rimi_scraper' -> 'barbora_scraper'
-- 4. MansRimi discount prices -> PALDIES discount prices (same column structure)
-- 5. Keep all other structure identical for shared reporting across stores

-- ============================================================================
-- DATA SHARING CONTRACT FOR EXTERNAL PROJECTS
-- ============================================================================
-- Use product_ingredient_cards view for product card display:
--
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
--   - suspicion_category: type of concern (sweetener, preservative, etc.)
--   - health_note: Latvian health warning (max 200 chars)
--
-- Refresh materialized view after daily updates:
-- REFRESH MATERIALIZED VIEW CONCURRENTLY product_ingredient_cards;
