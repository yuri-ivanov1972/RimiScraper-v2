-- Migration 004: Store the current ingredient/nutrition validation result
-- Applied to development during the nutrition validation rollout.

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