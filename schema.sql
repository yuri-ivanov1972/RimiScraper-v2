-- ============================================================
-- Rimi Product Scraper — Database Bootstrap Schema
-- Authoritative empty-schema definition; does not include source data
-- ============================================================

-- Required extension for trigram full-text search on product names
CREATE EXTENSION IF NOT EXISTS pg_trgm;


-- ============================================================
-- TABLES (in dependency order)
-- ============================================================

-- -----------------------------------------------------------
-- normalized_categories
-- Hierarchical category tree (level 1 = top, level 2 = sub)
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS normalized_categories (
    category_id             INTEGER PRIMARY KEY,
    rimi_category_code      TEXT UNIQUE,
    name_lv                 TEXT        NOT NULL,
    name_en                 TEXT,
    parent_category_id      INTEGER     REFERENCES normalized_categories (category_id),
    level                   INTEGER     NOT NULL,
    nova_score              INTEGER     CHECK (nova_score BETWEEN 1 AND 4),
    nova_score_explicit     BOOLEAN     NOT NULL DEFAULT FALSE,
    nutriscore_category_type TEXT       CHECK (nutriscore_category_type IN (
                                'general', 'beverage', 'cheese', 'red_meat',
                                'fat_oil_nut', 'full_fvn', 'half_fvn'
                            )),
    nutriscore_category_type_explicit BOOLEAN NOT NULL DEFAULT FALSE
);


-- -----------------------------------------------------------
-- products
-- One row per scraped product (SKU is the business key)
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS products (
    product_id          SERIAL PRIMARY KEY,
    sku                 TEXT        NOT NULL UNIQUE,
    name                TEXT        NOT NULL,
    name_norm           TEXT,
    rimi_url            TEXT        UNIQUE,
    category_id         INTEGER     NOT NULL REFERENCES normalized_categories (category_id),
    quantity_value      NUMERIC(10, 2),
    quantity_unit       VARCHAR(50),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    country_of_origin   VARCHAR(255)         DEFAULT 'Unknown',
    nutrition_source    VARCHAR(50),
    needs_enrichment    BOOLEAN              DEFAULT FALSE,
    enrichment_reviewed BOOLEAN              DEFAULT FALSE,
    enrichment_skipped      BOOLEAN              DEFAULT FALSE,
    has_confirmed_match     BOOLEAN              DEFAULT FALSE,
    nova_score              INTEGER              CHECK (nova_score BETWEEN 1 AND 4),
    nova_source             VARCHAR(30),
    is_hidden               BOOLEAN      NOT NULL DEFAULT FALSE
);


-- -----------------------------------------------------------
-- nutritionfacts
-- One row per product (1-to-1 via product_id)
-- Stores all per-100g nutritional values + Nutri-Score result
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS nutritionfacts (
    nutrition_id            SERIAL PRIMARY KEY,
    product_id              INTEGER     NOT NULL UNIQUE REFERENCES products (product_id),
    ingredients_text        TEXT,
    energy_kcal             INTEGER,
    energy_kj               INTEGER,
    fat_total               NUMERIC(10, 2),
    fat_saturated           NUMERIC(10, 2),
    carbs_total             NUMERIC(10, 2),
    carbs_sugars            NUMERIC(10, 2),
    protein                 NUMERIC(10, 2),
    salt                    NUMERIC(10, 2),
    fiber                   NUMERIC(10, 2),
    nutri_score_grade       CHAR(1),
    nutri_score_points      INTEGER,
    data_source_date        TIMESTAMPTZ,
    usda_fdc_id             INTEGER,
    nutrition_manual_edit   BOOLEAN              DEFAULT FALSE,
    is_fiber_correct        BOOLEAN              DEFAULT TRUE
);


-- -----------------------------------------------------------
-- nutrition_validation
-- One current rule-based ingredient/nutrition result per product
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS nutrition_validation (
    id                SERIAL PRIMARY KEY,
    product_id        INTEGER NOT NULL UNIQUE
                      REFERENCES products (product_id) ON DELETE CASCADE,
    suspicion_level   TEXT NOT NULL CHECK (suspicion_level IN ('none', 'low', 'medium', 'high')),
    suspicion_score   NUMERIC(10, 2) NOT NULL CHECK (suspicion_score >= 0),
    reasons           JSONB NOT NULL DEFAULT '[]'::jsonb
                      CHECK (jsonb_typeof(reasons) = 'array'),
    checked_at        TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);


-- -----------------------------------------------------------
-- product_price_history
-- Append-only price/availability log (never UPDATE — INSERT only)
-- Use DISTINCT ON (product_id) ORDER BY recorded_at DESC for current price
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS product_price_history (
    price_history_id        SERIAL PRIMARY KEY,
    product_id              INTEGER         NOT NULL REFERENCES products (product_id),
    price                   NUMERIC(10, 2)  NOT NULL,
    currency                VARCHAR(3)      NOT NULL DEFAULT 'EUR',
    is_available            BOOLEAN         NOT NULL,
    recorded_at             TIMESTAMPTZ     NOT NULL,
    data_source             VARCHAR(100),
    created_at              TIMESTAMPTZ     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    price_per_unit          NUMERIC(10, 4),
    price_per_unit_type     VARCHAR(20),
    discount_price          NUMERIC(10, 2),
    discount_price_per_unit NUMERIC(10, 4)
);


-- -----------------------------------------------------------
-- productphotos
-- One or more photo URLs per product (is_primary = main image)
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS productphotos (
    photo_id    SERIAL PRIMARY KEY,
    product_id  INTEGER NOT NULL REFERENCES products (product_id),
    photo_url   TEXT    NOT NULL,
    alt_text    TEXT,
    is_primary  BOOLEAN DEFAULT FALSE
);


-- -----------------------------------------------------------
-- ingredient_analysis
-- Deduped ingredient dictionary with AI-assigned categories
-- category: 'natural' | 'processed' | 'uncategorized'
-- suspicion_level: 'avoid' | 'limit' | 'caution' | 'clean'
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS ingredient_analysis (
    id                  SERIAL PRIMARY KEY,
    ingredient          TEXT        NOT NULL UNIQUE,
    frequency           INTEGER     NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    clean_name          TEXT,
    category            VARCHAR(20)          DEFAULT 'uncategorized',
    is_processed        BOOLEAN,
    suspicion_level     TEXT,
    suspicion_category  TEXT,
    health_note         TEXT
);


-- -----------------------------------------------------------
-- ingredient_product_mapping
-- Many-to-many: ingredient_analysis <-> products (by SKU)
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS ingredient_product_mapping (
    ingredient_id   INTEGER     NOT NULL REFERENCES ingredient_analysis (id),
    product_sku     TEXT        NOT NULL REFERENCES products (sku),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (ingredient_id, product_sku)
);


-- -----------------------------------------------------------
-- category_processing_jobs
-- Job queue for background worker — one job per category pass
-- status: 'queued' | 'in_progress' | 'completed' | 'failed'
-- update_mode: 'full' | 'incremental'
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS category_processing_jobs (
    id                  SERIAL PRIMARY KEY,
    category_code       VARCHAR(50)  NOT NULL,
    category_id         INTEGER,
    total_products      INTEGER      NOT NULL,
    processed_count     INTEGER               DEFAULT 0,
    status              VARCHAR(20)  NOT NULL DEFAULT 'in_progress',
    started_at          TIMESTAMP             DEFAULT CURRENT_TIMESTAMP,
    last_updated        TIMESTAMP             DEFAULT CURRENT_TIMESTAMP,
    completed_at        TIMESTAMP,
    priority            INTEGER               DEFAULT 5,
    scheduled_for       TIMESTAMP             DEFAULT CURRENT_TIMESTAMP,
    current_worker_id   VARCHAR(100),
    last_heartbeat      TIMESTAMP,
    retry_count         INTEGER               DEFAULT 0,
    max_retries         INTEGER               DEFAULT 3,
    lock_version        INTEGER               DEFAULT 0,
    log_path            TEXT,
    notes               TEXT,
    requested_by        VARCHAR(100)          DEFAULT 'streamlit_ui',
    update_mode         VARCHAR(20)  NOT NULL DEFAULT 'full'
);


-- -----------------------------------------------------------
-- processing_workers
-- Registry of active background worker processes
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS processing_workers (
    id              SERIAL PRIMARY KEY,
    worker_id       VARCHAR(100) NOT NULL UNIQUE,
    hostname        VARCHAR(255),
    pid             INTEGER,
    status          VARCHAR(20)  NOT NULL DEFAULT 'idle',
    current_job_id  INTEGER      REFERENCES category_processing_jobs (id),
    last_heartbeat  TIMESTAMP             DEFAULT CURRENT_TIMESTAMP,
    started_at      TIMESTAMP             DEFAULT CURRENT_TIMESTAMP,
    stopped_at      TIMESTAMP,
    error_message   TEXT
);


-- -----------------------------------------------------------
-- job_events
-- Append-only event log for each processing job
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS job_events (
    id          SERIAL PRIMARY KEY,
    job_id      INTEGER      NOT NULL REFERENCES category_processing_jobs (id),
    event_type  VARCHAR(50)  NOT NULL,
    message     TEXT,
    created_at  TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    metadata    JSONB
);


-- -----------------------------------------------------------
-- product_processing_log
-- Per-SKU result log for each job run
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS product_processing_log (
    id              SERIAL PRIMARY KEY,
    job_id          INTEGER      NOT NULL REFERENCES category_processing_jobs (id),
    sku             VARCHAR(50)  NOT NULL,
    status          VARCHAR(20)  NOT NULL DEFAULT 'pending',
    error_message   TEXT,
    processed_at    TIMESTAMP             DEFAULT CURRENT_TIMESTAMP
);


-- -----------------------------------------------------------
-- update_statistics
-- Aggregated counters per job/category run
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS update_statistics (
    id                      SERIAL PRIMARY KEY,
    job_id                  INTEGER      NOT NULL REFERENCES category_processing_jobs (id),
    category_code           VARCHAR(50)  NOT NULL,
    total_checked           INTEGER               DEFAULT 0,
    new_products            INTEGER               DEFAULT 0,
    price_changed           INTEGER               DEFAULT 0,
    availability_changed    INTEGER               DEFAULT 0,
    data_updated            INTEGER               DEFAULT 0,
    unchanged               INTEGER               DEFAULT 0,
    failed                  INTEGER               DEFAULT 0,
    created_at              TIMESTAMP             DEFAULT CURRENT_TIMESTAMP
);


-- -----------------------------------------------------------
-- daily_update_logs
-- One summary row per scheduled daily update run
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS daily_update_logs (
    id                      SERIAL PRIMARY KEY,
    update_type             VARCHAR(50)  NOT NULL DEFAULT 'daily',
    start_time              TIMESTAMP    NOT NULL,
    end_time                TIMESTAMP    NOT NULL,
    duration_minutes        NUMERIC(10, 2),
    categories_processed    INTEGER               DEFAULT 0,
    jobs_completed          INTEGER               DEFAULT 0,
    jobs_failed             INTEGER               DEFAULT 0,
    products_added          INTEGER               DEFAULT 0,
    products_updated        INTEGER               DEFAULT 0,
    products_removed        INTEGER               DEFAULT 0,
    price_changes_count     INTEGER               DEFAULT 0,
    availability_changes    JSONB,
    ingredient_changes_count INTEGER              DEFAULT 0,
    nutrition_changes_count INTEGER               DEFAULT 0,
    photo_changes_count     INTEGER               DEFAULT 0,
    errors_count            INTEGER               DEFAULT 0,
    error_details           JSONB,
    summary                 TEXT,
    created_at              TIMESTAMP             DEFAULT CURRENT_TIMESTAMP
);


-- ============================================================
-- INDEXES
-- ============================================================

-- These additive statements keep the bootstrap safe for databases created
-- from an earlier version of this schema.
ALTER TABLE products
    ADD COLUMN IF NOT EXISTS nova_score INTEGER CHECK (nova_score BETWEEN 1 AND 4),
    ADD COLUMN IF NOT EXISTS nova_source VARCHAR(30),
    ADD COLUMN IF NOT EXISTS is_hidden BOOLEAN NOT NULL DEFAULT FALSE;

-- normalized_categories
CREATE INDEX IF NOT EXISTS idx_normalized_categories_nova ON normalized_categories (nova_score);

-- products
CREATE INDEX IF NOT EXISTS idx_products_sku         ON products (sku);
CREATE INDEX IF NOT EXISTS idx_products_category_id ON products (category_id);
CREATE INDEX IF NOT EXISTS idx_products_name        ON products USING gin (name gin_trgm_ops);

-- nutritionfacts
CREATE INDEX IF NOT EXISTS idx_nutrition_product_id  ON nutritionfacts (product_id);
CREATE INDEX IF NOT EXISTS idx_nutrition_nutri_score ON nutritionfacts (nutri_score_grade);
CREATE INDEX IF NOT EXISTS idx_nutrition_protein     ON nutritionfacts (protein);
CREATE INDEX IF NOT EXISTS idx_nutrition_carbs_sugars ON nutritionfacts (carbs_sugars);

-- nutrition_validation
CREATE INDEX IF NOT EXISTS idx_nutrition_validation_score
    ON nutrition_validation (suspicion_score DESC);
CREATE INDEX IF NOT EXISTS idx_nutrition_validation_level
    ON nutrition_validation (suspicion_level);

CREATE OR REPLACE VIEW nutrition_validation_report AS
SELECT
    p.product_id,
    p.sku,
    p.name AS product,
    nv.suspicion_level,
    nv.suspicion_score,
    nv.reasons,
    nv.checked_at
FROM nutrition_validation nv
JOIN products p ON p.product_id = nv.product_id
ORDER BY nv.suspicion_score DESC, p.product_id;

CREATE OR REPLACE VIEW nutrition_validation_summary AS
SELECT
    COUNT(*) AS products_checked,
    COUNT(*) FILTER (WHERE suspicion_level = 'none') AS none_count,
    COUNT(*) FILTER (WHERE suspicion_level = 'low') AS low_count,
    COUNT(*) FILTER (WHERE suspicion_level = 'medium') AS medium_count,
    COUNT(*) FILTER (WHERE suspicion_level = 'high') AS high_count
FROM nutrition_validation;

CREATE OR REPLACE VIEW nutrition_validation_rule_summary AS
SELECT
    reason ->> 'rule' AS rule,
    COUNT(*) AS product_count,
    ROUND(
        COUNT(*) * 100.0 / NULLIF((SELECT COUNT(*) FROM nutrition_validation), 0),
        2
    ) AS product_percentage
FROM nutrition_validation nv
CROSS JOIN LATERAL jsonb_array_elements(nv.reasons) reason
GROUP BY reason ->> 'rule'
ORDER BY product_count DESC, rule;

-- product_price_history
CREATE INDEX IF NOT EXISTS idx_price_history_product_id       ON product_price_history (product_id);
CREATE INDEX IF NOT EXISTS idx_price_history_recorded_at      ON product_price_history (recorded_at);
CREATE INDEX IF NOT EXISTS idx_price_history_product_recorded ON product_price_history (product_id, recorded_at);
CREATE INDEX IF NOT EXISTS idx_price_history_availability     ON product_price_history (is_available);
CREATE INDEX IF NOT EXISTS idx_price_history_data_source      ON product_price_history (data_source);

-- productphotos
CREATE INDEX IF NOT EXISTS idx_photos_product_id ON productphotos (product_id);

-- ingredient_analysis
CREATE INDEX IF NOT EXISTS idx_ingredient_analysis_freq       ON ingredient_analysis (frequency DESC);
CREATE INDEX IF NOT EXISTS idx_ingredient_analysis_category   ON ingredient_analysis (category);
CREATE INDEX IF NOT EXISTS idx_ingredient_analysis_processed  ON ingredient_analysis (is_processed);
CREATE INDEX IF NOT EXISTS idx_ingredient_analysis_suspicion  ON ingredient_analysis (suspicion_level);

-- ingredient_product_mapping
CREATE INDEX IF NOT EXISTS idx_ingredient_product_mapping_ingredient ON ingredient_product_mapping (ingredient_id);
CREATE INDEX IF NOT EXISTS idx_ingredient_product_mapping_sku        ON ingredient_product_mapping (product_sku);

-- category_processing_jobs
CREATE INDEX IF NOT EXISTS idx_category_jobs_status ON category_processing_jobs (status);
CREATE INDEX IF NOT EXISTS idx_category_jobs_code   ON category_processing_jobs (category_code);
CREATE INDEX IF NOT EXISTS idx_jobs_queue_poll      ON category_processing_jobs (status, priority DESC, scheduled_for)
    WHERE status IN ('queued', 'in_progress');
CREATE UNIQUE INDEX IF NOT EXISTS idx_unique_active_category ON category_processing_jobs (category_code)
    WHERE status IN ('queued', 'in_progress');

-- processing_workers
CREATE UNIQUE INDEX IF NOT EXISTS idx_workers_status      ON processing_workers (status, last_heartbeat DESC);
CREATE INDEX IF NOT EXISTS idx_workers_current_job ON processing_workers (current_job_id)
    WHERE current_job_id IS NOT NULL;

-- job_events
CREATE INDEX IF NOT EXISTS idx_job_events_job  ON job_events (job_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_job_events_type ON job_events (event_type, created_at DESC);

-- product_processing_log
CREATE INDEX IF NOT EXISTS idx_product_log_job    ON product_processing_log (job_id);
CREATE INDEX IF NOT EXISTS idx_product_log_sku    ON product_processing_log (sku);
CREATE INDEX IF NOT EXISTS idx_product_log_status ON product_processing_log (job_id, status);

-- update_statistics
CREATE INDEX IF NOT EXISTS idx_update_statistics_job_id        ON update_statistics (job_id);
CREATE INDEX IF NOT EXISTS idx_update_statistics_category_code ON update_statistics (category_code);

-- daily_update_logs
CREATE INDEX IF NOT EXISTS idx_daily_update_logs_start_time  ON daily_update_logs (start_time DESC);
CREATE INDEX IF NOT EXISTS idx_daily_update_logs_created_at  ON daily_update_logs (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_daily_update_logs_update_type ON daily_update_logs (update_type);


-- ============================================================
-- MATERIALIZED VIEW
-- Shared with external projects
-- Refresh with: REFRESH MATERIALIZED VIEW CONCURRENTLY product_ingredient_cards;
-- ============================================================

CREATE MATERIALIZED VIEW IF NOT EXISTS product_ingredient_cards AS
SELECT
    p.sku,
    p.name,
    p.category_id,
    nc.name_lv AS category_name,
    COALESCE(
        jsonb_agg(
            jsonb_build_object(
                'id',                 ia.id,
                'name',               COALESCE(ia.clean_name, ia.ingredient),
                'category',           ia.category,
                'is_processed',       ia.is_processed,
                'suspicion_level',    ia.suspicion_level,
                'suspicion_category', ia.suspicion_category,
                'health_note',        ia.health_note
            ) ORDER BY ia.frequency DESC
        ) FILTER (WHERE ia.id IS NOT NULL),
        '[]'::jsonb
    ) AS ingredients,
    COUNT(ia.id) FILTER (WHERE ia.category = 'natural')   AS natural_count,
    COUNT(ia.id) FILTER (WHERE ia.category = 'processed') AS processed_count,
    COUNT(ia.id) FILTER (WHERE ia.suspicion_level = 'avoid')   AS avoid_count,
    COUNT(ia.id) FILTER (WHERE ia.suspicion_level = 'limit')   AS limit_count,
    COUNT(ia.id) FILTER (WHERE ia.suspicion_level = 'caution') AS caution_count
FROM products p
LEFT JOIN normalized_categories nc    ON p.category_id  = nc.category_id
LEFT JOIN ingredient_product_mapping ipm ON p.sku       = ipm.product_sku
LEFT JOIN ingredient_analysis ia         ON ipm.ingredient_id = ia.id
GROUP BY p.sku, p.name, p.category_id, nc.name_lv;

-- Unique index required for CONCURRENT refresh
CREATE UNIQUE INDEX IF NOT EXISTS idx_product_ingredient_cards_sku ON product_ingredient_cards (sku);
