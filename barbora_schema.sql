-- Barbora Product Scraper - Database Schema
-- Identical to Rimi scraper schema, adapted for Barbora.lv
-- Run this in the new project after creating PostgreSQL database

-- ============================================================
-- CATEGORIES
-- ============================================================

CREATE TABLE normalized_categories (
    category_id INTEGER PRIMARY KEY,
    barbora_category_code TEXT,  -- Renamed from rimi_category_code
    name_lv TEXT NOT NULL,
    name_en TEXT,
    parent_category_id INTEGER REFERENCES normalized_categories(category_id),
    level INTEGER NOT NULL
);

CREATE INDEX idx_normalized_categories_code ON normalized_categories(barbora_category_code);
CREATE INDEX idx_normalized_categories_parent ON normalized_categories(parent_category_id);
CREATE INDEX idx_normalized_categories_level ON normalized_categories(level);

-- ============================================================
-- PRODUCTS
-- ============================================================

CREATE TABLE products (
    product_id SERIAL PRIMARY KEY,
    sku TEXT NOT NULL UNIQUE,  -- Barbora item_id from GA4 data
    name TEXT NOT NULL,
    name_norm TEXT,  -- Normalized name for matching
    barbora_url TEXT,  -- Renamed from rimi_url
    category_id INTEGER NOT NULL REFERENCES normalized_categories(category_id),
    quantity_value NUMERIC,
    quantity_unit VARCHAR(50),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    country_of_origin VARCHAR(255) DEFAULT 'Unknown',
    nutrition_source VARCHAR(50),  -- 'barbora_scraped', 'ai_generated', 'manual_entry'
    needs_enrichment BOOLEAN DEFAULT FALSE,
    enrichment_reviewed BOOLEAN DEFAULT FALSE,
    enrichment_skipped BOOLEAN DEFAULT FALSE
);

CREATE INDEX idx_products_sku ON products(sku);
CREATE INDEX idx_products_category ON products(category_id);
CREATE INDEX idx_products_name_norm ON products(name_norm);
CREATE INDEX idx_products_needs_enrichment ON products(needs_enrichment);

-- ============================================================
-- PRICE HISTORY (all price/availability tracking)
-- ============================================================

CREATE TABLE product_price_history (
    price_history_id SERIAL PRIMARY KEY,
    product_id INTEGER NOT NULL REFERENCES products(product_id),
    price NUMERIC NOT NULL,
    currency VARCHAR(3) NOT NULL DEFAULT 'EUR',
    is_available BOOLEAN NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL,
    data_source VARCHAR(100),  -- 'category_listing', 'product_page'
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    price_per_unit NUMERIC,
    price_per_unit_type VARCHAR(20),  -- 'kg', 'l', 'gab'
    discount_price NUMERIC,  -- PALDIES card price (like MansRimi)
    discount_price_per_unit NUMERIC
);

CREATE INDEX idx_price_history_product ON product_price_history(product_id);
CREATE INDEX idx_price_history_recorded ON product_price_history(recorded_at);
CREATE INDEX idx_price_history_product_recorded ON product_price_history(product_id, recorded_at DESC);

-- ============================================================
-- NUTRITION FACTS
-- ============================================================

CREATE TABLE nutritionfacts (
    nutrition_id SERIAL PRIMARY KEY,
    product_id INTEGER NOT NULL REFERENCES products(product_id),
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
    nutri_score_grade CHAR(1),  -- A, B, C, D, E
    nutri_score_points INTEGER,
    data_source_date TIMESTAMPTZ,
    usda_fdc_id INTEGER  -- For USDA enrichment
);

CREATE INDEX idx_nutritionfacts_product ON nutritionfacts(product_id);
CREATE INDEX idx_nutritionfacts_nutriscore ON nutritionfacts(nutri_score_grade);

-- ============================================================
-- PRODUCT PHOTOS
-- ============================================================

CREATE TABLE productphotos (
    photo_id SERIAL PRIMARY KEY,
    product_id INTEGER NOT NULL REFERENCES products(product_id),
    photo_url TEXT NOT NULL,
    alt_text TEXT,
    is_primary BOOLEAN DEFAULT FALSE
);

CREATE INDEX idx_productphotos_product ON productphotos(product_id);

-- ============================================================
-- INGREDIENT ANALYSIS (E-numbers)
-- ============================================================

CREATE TABLE ingredient_analysis (
    id SERIAL PRIMARY KEY,
    ingredient TEXT NOT NULL,
    frequency INTEGER NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE ingredient_product_mapping (
    ingredient_id INTEGER NOT NULL REFERENCES ingredient_analysis(id),
    product_sku TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (ingredient_id, product_sku)
);

-- ============================================================
-- JOB QUEUE SYSTEM
-- ============================================================

CREATE TABLE category_processing_jobs (
    id SERIAL PRIMARY KEY,
    category_code VARCHAR(50) NOT NULL,
    category_id INTEGER REFERENCES normalized_categories(category_id),
    total_products INTEGER NOT NULL,
    processed_count INTEGER DEFAULT 0,
    status VARCHAR(20) NOT NULL DEFAULT 'in_progress',
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    priority INTEGER DEFAULT 5,
    scheduled_for TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    current_worker_id VARCHAR(100),
    last_heartbeat TIMESTAMP,
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,
    lock_version INTEGER DEFAULT 0,
    log_path TEXT,
    notes TEXT,
    requested_by VARCHAR(100) DEFAULT 'streamlit_ui',
    update_mode VARCHAR(20) NOT NULL DEFAULT 'full'  -- 'full' or 'incremental'
);

CREATE INDEX idx_jobs_status ON category_processing_jobs(status);
CREATE INDEX idx_jobs_category ON category_processing_jobs(category_code);
CREATE INDEX idx_jobs_priority ON category_processing_jobs(priority DESC, scheduled_for);
CREATE INDEX idx_jobs_worker ON category_processing_jobs(current_worker_id);

-- ============================================================
-- JOB EVENTS (lifecycle tracking)
-- ============================================================

CREATE TABLE job_events (
    id SERIAL PRIMARY KEY,
    job_id INTEGER NOT NULL REFERENCES category_processing_jobs(id),
    event_type VARCHAR(50) NOT NULL,
    message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    metadata JSONB
);

CREATE INDEX idx_job_events_job ON job_events(job_id);
CREATE INDEX idx_job_events_type ON job_events(event_type);

-- ============================================================
-- PROCESSING WORKERS
-- ============================================================

CREATE TABLE processing_workers (
    id SERIAL PRIMARY KEY,
    worker_id VARCHAR(100) NOT NULL UNIQUE,
    hostname VARCHAR(255),
    pid INTEGER,
    status VARCHAR(20) NOT NULL DEFAULT 'idle',
    current_job_id INTEGER REFERENCES category_processing_jobs(id),
    last_heartbeat TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    stopped_at TIMESTAMP,
    error_message TEXT
);

CREATE INDEX idx_workers_status ON processing_workers(status);
CREATE INDEX idx_workers_heartbeat ON processing_workers(last_heartbeat);

-- ============================================================
-- PRODUCT PROCESSING LOG (per-product status within jobs)
-- ============================================================

CREATE TABLE product_processing_log (
    id SERIAL PRIMARY KEY,
    job_id INTEGER NOT NULL REFERENCES category_processing_jobs(id),
    sku VARCHAR(50) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    error_message TEXT,
    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_processing_log_job ON product_processing_log(job_id);
CREATE INDEX idx_processing_log_sku ON product_processing_log(sku);

-- ============================================================
-- UPDATE STATISTICS (per-job metrics)
-- ============================================================

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

CREATE INDEX idx_update_stats_job ON update_statistics(job_id);
CREATE INDEX idx_update_stats_category ON update_statistics(category_code);

-- ============================================================
-- DAILY UPDATE LOGS (summary reports)
-- ============================================================

CREATE TABLE daily_update_logs (
    id SERIAL PRIMARY KEY,
    update_type VARCHAR(50) NOT NULL DEFAULT 'daily',
    start_time TIMESTAMP NOT NULL,
    end_time TIMESTAMP NOT NULL,
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
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_daily_logs_type ON daily_update_logs(update_type);
CREATE INDEX idx_daily_logs_start ON daily_update_logs(start_time);
