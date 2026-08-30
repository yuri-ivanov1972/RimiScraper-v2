-- Migration 005: normalized Rimi brand and producer master data.

CREATE TABLE IF NOT EXISTS brands (
    brand_id        SERIAL PRIMARY KEY,
    name            TEXT NOT NULL,
    normalized_name TEXT NOT NULL UNIQUE,
    website_url     TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS producers (
    producer_id     SERIAL PRIMARY KEY,
    name            TEXT NOT NULL,
    normalized_name TEXT NOT NULL UNIQUE,
    website_url     TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE products
    ADD COLUMN IF NOT EXISTS brand_id INTEGER REFERENCES brands (brand_id),
    ADD COLUMN IF NOT EXISTS producer_id INTEGER REFERENCES producers (producer_id);

CREATE TABLE IF NOT EXISTS brand_producers (
    brand_id    INTEGER NOT NULL REFERENCES brands (brand_id) ON DELETE CASCADE,
    producer_id INTEGER NOT NULL REFERENCES producers (producer_id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (brand_id, producer_id)
);

CREATE INDEX IF NOT EXISTS idx_products_brand_id
    ON products (brand_id);
CREATE INDEX IF NOT EXISTS idx_products_producer_id
    ON products (producer_id);
CREATE INDEX IF NOT EXISTS idx_brand_producers_producer_id
    ON brand_producers (producer_id);