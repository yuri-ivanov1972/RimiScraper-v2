-- Barbora Product Scraper Database Schema
-- PostgreSQL 16
-- Generated: 2026-01-11
-- 
-- This schema supports a grocery price tracking system that:
-- - Tracks products, categories, prices, and availability over time
-- - Stores nutrition facts and product photos
-- - Manages scraping jobs and worker processes
-- - Supports lightweight daily price updates

-- ============================================================================
-- CORE TABLES
-- ============================================================================

-- Normalized category hierarchy from Barbora
CREATE TABLE normalized_categories (
    category_id INTEGER PRIMARY KEY,
    barbora_category_code TEXT,
    name_lv TEXT NOT NULL,
    name_en TEXT,
    parent_category_id INTEGER REFERENCES normalized_categories(category_id),
    level INTEGER NOT NULL,
    normalized_category TEXT
);

CREATE INDEX idx_normalized_categories_code ON normalized_categories (barbora_category_code);
CREATE INDEX idx_normalized_categories_level ON normalized_categories (level);
CREATE INDEX idx_normalized_categories_parent ON normalized_categories (parent_category_id);

-- Products table (core product data without price)
CREATE TABLE products (
    product_id SERIAL PRIMARY KEY,
    sku TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    name_norm TEXT,
    barbora_url TEXT,
    category_id INTEGER NOT NULL REFERENCES normalized_categories(category_id),
    quantity_value NUMERIC,
    quantity_unit VARCHAR(50),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    country_of_origin VARCHAR(255) DEFAULT 'Unknown',
    nutrition_source VARCHAR(50),
    needs_enrichment BOOLEAN DEFAULT false,
    enrichment_reviewed BOOLEAN DEFAULT false,
    enrichment_skipped BOOLEAN DEFAULT false,
    ingredients TEXT,
    allergens TEXT,
    description TEXT,
    rimi_category_code INTEGER
);

CREATE INDEX idx_products_sku ON products (sku);
CREATE INDEX idx_products_category ON products (category_id);
CREATE INDEX idx_products_name_norm ON products (name_norm);
CREATE INDEX idx_products_needs_enrichment ON products (needs_enrichment);

-- Price history (all price and availability tracking happens here)
CREATE TABLE product_price_history (
    price_history_id SERIAL PRIMARY KEY,
    product_id INTEGER NOT NULL REFERENCES products(product_id),
    price NUMERIC NOT NULL,
    currency VARCHAR(3) NOT NULL DEFAULT 'EUR',
    is_available BOOLEAN NOT NULL,
    recorded_at TIMESTAMP WITH TIME ZONE NOT NULL,
    data_source VARCHAR(100),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    price_per_unit NUMERIC,
    price_per_unit_type VARCHAR(20),
    discount_price NUMERIC,
    discount_price_per_unit NUMERIC
);

CREATE INDEX idx_price_history_product ON product_price_history (product_id);
CREATE INDEX idx_price_history_recorded ON product_price_history (recorded_at);
CREATE INDEX idx_price_history_product_recorded ON product_price_history (product_id, recorded_at DESC);

-- Nutrition facts (one per product)
CREATE TABLE nutritionfacts (
    nutrition_id SERIAL PRIMARY KEY,
    product_id INTEGER NOT NULL REFERENCES products(product_id) UNIQUE,
    ingredients_text TEXT,
    energy_kcal INTEGER,
    energy_kj INTEGER,
    fat_total NUMERIC,
    fat_saturated NUMERIC,
    carbs_total NUMERIC,
    carbs_sugars NUMERIC,
    protein NUMERIC,
    salt NUMERIC,
    fiber NUMERIC,
    nutri_score_grade CHAR(1),
    nutri_score_points INTEGER,
    data_source_date TIMESTAMP WITH TIME ZONE,
    usda_fdc_id INTEGER
);

CREATE INDEX idx_nutritionfacts_product ON nutritionfacts (product_id);
CREATE INDEX idx_nutritionfacts_nutriscore ON nutritionfacts (nutri_score_grade);

-- Product photos
CREATE TABLE productphotos (
    photo_id SERIAL PRIMARY KEY,
    product_id INTEGER NOT NULL REFERENCES products(product_id),
    photo_url TEXT NOT NULL,
    alt_text TEXT,
    is_primary BOOLEAN DEFAULT false
);

CREATE INDEX idx_productphotos_product ON productphotos (product_id);

-- ============================================================================
-- JOB PROCESSING TABLES
-- ============================================================================

-- Category processing jobs (job queue)
CREATE TABLE category_processing_jobs (
    id SERIAL PRIMARY KEY,
    category_code VARCHAR(50) NOT NULL,
    category_id INTEGER REFERENCES normalized_categories(category_id),
    total_products INTEGER NOT NULL,
    processed_count INTEGER DEFAULT 0,
    status VARCHAR(30) NOT NULL DEFAULT 'in_progress',
    started_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    last_updated TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP WITHOUT TIME ZONE,
    priority INTEGER DEFAULT 5,
    scheduled_for TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    current_worker_id VARCHAR(100),
    last_heartbeat TIMESTAMP WITHOUT TIME ZONE,
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,
    lock_version INTEGER DEFAULT 0,
    log_path TEXT,
    notes TEXT,
    requested_by VARCHAR(100) DEFAULT 'streamlit_ui',
    update_mode VARCHAR(20) NOT NULL DEFAULT 'full'
);

CREATE INDEX idx_jobs_category ON category_processing_jobs (category_code);
CREATE INDEX idx_jobs_status ON category_processing_jobs (status);
CREATE INDEX idx_jobs_priority ON category_processing_jobs (priority DESC, scheduled_for);
CREATE INDEX idx_jobs_worker ON category_processing_jobs (current_worker_id);

-- Job events (lifecycle tracking)
CREATE TABLE job_events (
    id SERIAL PRIMARY KEY,
    job_id INTEGER NOT NULL REFERENCES category_processing_jobs(id),
    event_type VARCHAR(50) NOT NULL,
    message TEXT,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    metadata JSONB
);

CREATE INDEX idx_job_events_job ON job_events (job_id);
CREATE INDEX idx_job_events_type ON job_events (event_type);

-- Worker registration
CREATE TABLE processing_workers (
    id SERIAL PRIMARY KEY,
    worker_id VARCHAR(100) NOT NULL UNIQUE,
    hostname VARCHAR(255),
    pid INTEGER,
    status VARCHAR(20) NOT NULL DEFAULT 'idle',
    current_job_id INTEGER REFERENCES category_processing_jobs(id),
    last_heartbeat TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    stopped_at TIMESTAMP WITHOUT TIME ZONE,
    error_message TEXT
);

CREATE INDEX idx_workers_status ON processing_workers (status);
CREATE INDEX idx_workers_heartbeat ON processing_workers (last_heartbeat);

-- Product processing log (per-product status within a job)
CREATE TABLE product_processing_log (
    id SERIAL PRIMARY KEY,
    job_id INTEGER NOT NULL REFERENCES category_processing_jobs(id),
    sku VARCHAR(50) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    error_message TEXT,
    processed_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    product_url TEXT,
    price NUMERIC(10,2),
    retail_price NUMERIC(10,2),
    price_per_unit NUMERIC(10,2),
    price_per_unit_type VARCHAR(20),
    is_available BOOLEAN DEFAULT true,
    promotion_data JSONB
);

CREATE INDEX idx_processing_log_job ON product_processing_log (job_id);
CREATE INDEX idx_processing_log_sku ON product_processing_log (sku);

-- ============================================================================
-- STATISTICS AND LOGGING TABLES
-- ============================================================================

-- Update statistics per job/category
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
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_update_stats_job ON update_statistics (job_id);
CREATE INDEX idx_update_stats_category ON update_statistics (category_code);

-- Daily update logs (full scrape summaries)
CREATE TABLE daily_update_logs (
    id SERIAL PRIMARY KEY,
    update_type VARCHAR(50) NOT NULL DEFAULT 'daily',
    start_time TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    end_time TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    duration_minutes NUMERIC,
    categories_processed INTEGER DEFAULT 0,
    jobs_completed INTEGER DEFAULT 0,
    jobs_failed INTEGER DEFAULT 0,
    products_added INTEGER DEFAULT 0,
    products_updated INTEGER DEFAULT 0,
    products_removed INTEGER DEFAULT 0,
    price_changes_count INTEGER DEFAULT 0,
    availability_changes JSONB,
    ingredient_changes_count INTEGER DEFAULT 0,
    nutrition_changes_count INTEGER DEFAULT 0,
    photo_changes_count INTEGER DEFAULT 0,
    errors_count INTEGER DEFAULT 0,
    error_details JSONB,
    summary TEXT,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_daily_logs_start ON daily_update_logs (start_time);
CREATE INDEX idx_daily_logs_type ON daily_update_logs (update_type);

-- Lightweight update run history
CREATE TABLE lightweight_update_runs (
    run_id SERIAL PRIMARY KEY,
    started_at TIMESTAMP WITHOUT TIME ZONE,
    ended_at TIMESTAMP WITHOUT TIME ZONE,
    duration_seconds DOUBLE PRECISION,
    categories_processed INTEGER DEFAULT 0,
    products_checked INTEGER DEFAULT 0,
    products_updated INTEGER DEFAULT 0,
    price_changes INTEGER DEFAULT 0,
    availability_changes INTEGER DEFAULT 0,
    new_products_found INTEGER DEFAULT 0,
    new_product_jobs_created INTEGER DEFAULT 0,
    errors_count INTEGER DEFAULT 0,
    status VARCHAR(50) DEFAULT 'running',
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================================
-- INGREDIENT ANALYSIS TABLES
-- ============================================================================

-- Unique ingredients with frequency counts
CREATE TABLE ingredient_analysis (
    id SERIAL PRIMARY KEY,
    ingredient TEXT NOT NULL,
    frequency INTEGER NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX ingredient_analysis_ingredient_idx ON ingredient_analysis (ingredient);

-- Ingredient to product mapping
CREATE TABLE ingredient_product_mapping (
    ingredient_id INTEGER NOT NULL REFERENCES ingredient_analysis(id),
    product_sku TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (ingredient_id, product_sku)
);

-- ============================================================================
-- NOTES
-- ============================================================================
-- 
-- Key Design Decisions:
-- 1. Price/availability stored in product_price_history, NOT in products table
-- 2. To get current price: SELECT latest record from product_price_history using LATERAL JOIN
-- 3. To update price: INSERT new record into product_price_history
-- 4. Categories use hierarchical structure with parent_category_id self-reference
-- 5. Job queue supports priority scheduling, heartbeat monitoring, and stale job reassignment
-- 
-- Price Fields:
-- - price: Regular/base price
-- - discount_price: Discounted sale price (when product is on promotion)
-- - price_per_unit: Price per kg/L for comparison
-- 
-- Data Sources (data_source column):
-- - 'barbora_scrape': Full product page scraping
-- - 'lightweight_update': Fast price update from category listing JSON
--
-- Cross-store matching:
-- - rimi_category_code: Links Barbora products to Rimi category IDs for price comparison
