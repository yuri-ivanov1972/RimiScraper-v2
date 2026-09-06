"""Durable queue and validation helpers for suspicious-product refresh jobs."""

from __future__ import annotations

from typing import Any

from psycopg2.extras import Json, RealDictCursor

from nutrition_validation_backfill import INGREDIENT_BATCH_QUERY, UPSERT_QUERY
from nutrition_validator import NutritionValidator, enrich_mapped_ingredients


JOB_TYPE = "suspicious_refresh"
ACTIVE_STATUSES = ("queued", "in_progress")
REQUIRED_PRODUCT_STATUSES = {
    "pending",
    "processing",
    "scraped",
    "validating",
    "completed",
    "failed",
    "skipped",
}


def is_active_refresh_job(job: dict[str, Any] | None) -> bool:
    """Return an explicit boolean suitable for Streamlit widget properties."""
    return bool(job and job.get("status") in ACTIVE_STATUSES)


def verify_refresh_schema(connection) -> None:
    """Fail before scraping if the database lacks refresh status support."""
    with connection.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(
            """
            SELECT string_agg(pg_get_constraintdef(oid), ' ') AS definition
            FROM pg_constraint
            WHERE conrelid = 'product_processing_log'::regclass
              AND contype = 'c'
            """
        )
        row = cursor.fetchone()
    definition = (row.get("definition") if row else None) or ""
    if not definition:
        return
    missing = sorted(
        status
        for status in REQUIRED_PRODUCT_STATUSES
        if f"'{status}'" not in definition
    )
    if missing:
        raise RuntimeError(
            "Database migration 007 is required; unsupported product statuses: "
            + ", ".join(missing)
        )


def queue_suspicious_refresh(connection, requested_by: str = "checks_ui") -> tuple[int, int]:
    """Snapshot all currently suspicious products into one durable job."""
    with connection.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (JOB_TYPE,))
        cursor.execute(
            """
            SELECT id
            FROM category_processing_jobs
            WHERE job_type = %s AND status IN ('queued', 'in_progress')
            LIMIT 1
            """,
            (JOB_TYPE,),
        )
        active = cursor.fetchone()
        if active:
            raise ValueError(f"Refresh job #{active['id']} is already active")

        cursor.execute(
            """
            SELECT p.product_id, p.sku
            FROM nutrition_validation nv
            JOIN products p ON p.product_id = nv.product_id
            WHERE nv.suspicion_score > 0
              AND p.sku IS NOT NULL
            ORDER BY nv.suspicion_score DESC, p.product_id
            """
        )
        products = cursor.fetchall()
        if not products:
            raise ValueError("No suspicious products are available to refresh")

        cursor.execute(
            """
            INSERT INTO category_processing_jobs (
                category_code, category_id, total_products, processed_count,
                status, priority, requested_by, update_mode, job_type, phase
            )
            VALUES (NULL, NULL, %s, 0, 'queued', 7, %s, 'full', %s, 'queued')
            RETURNING id
            """,
            (len(products), requested_by, JOB_TYPE),
        )
        job_id = cursor.fetchone()["id"]

        cursor.executemany(
            """
            INSERT INTO product_processing_log (
                job_id, sku, product_id, status, scrape_status, validation_status
            )
            VALUES (%s, %s, %s, 'pending', 'pending', 'pending')
            """,
            [(job_id, row["sku"], row["product_id"]) for row in products],
        )
        cursor.execute(
            """
            INSERT INTO job_events (job_id, event_type, message, metadata)
            VALUES (%s, 'job_created', %s, %s)
            """,
            (
                job_id,
                f"Queued full refresh for {len(products)} suspicious products",
                Json({"job_type": JOB_TYPE, "products": len(products)}),
            ),
        )
    connection.commit()
    return job_id, len(products)


def get_latest_refresh_status(connection) -> dict[str, Any] | None:
    """Return the latest refresh job with durable per-phase product counts."""
    with connection.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(
            """
            SELECT id, status, phase, total_products, processed_count,
                   validation_completed_count, validation_failed_count,
                   started_at, last_updated, completed_at
            FROM category_processing_jobs
            WHERE job_type = %s
            ORDER BY id DESC
            LIMIT 1
            """,
            (JOB_TYPE,),
        )
        job = cursor.fetchone()
        if not job:
            return None

        cursor.execute(
            """
            SELECT
                COUNT(*) FILTER (WHERE scrape_status = 'pending') AS queued,
                COUNT(*) FILTER (WHERE scrape_status = 'processing') AS scraping,
                COUNT(*) FILTER (
                    WHERE scrape_status = 'completed'
                      AND validation_status IN ('pending', 'processing')
                ) AS validating,
                COUNT(*) FILTER (WHERE status = 'completed') AS completed,
                COUNT(*) FILTER (WHERE status = 'failed') AS failed
            FROM product_processing_log
            WHERE job_id = %s
            """,
            (job["id"],),
        )
        counts = cursor.fetchone()
    return {**dict(job), **dict(counts)}


def get_refresh_failures(
    connection, job_id: int, limit: int = 20
) -> list[dict[str, Any]]:
    """Return recent per-product failures for display in the Checks tab."""
    with connection.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(
            """
            SELECT sku, error_message, processed_at
            FROM product_processing_log
            WHERE job_id = %s AND status = 'failed'
            ORDER BY processed_at DESC, id DESC
            LIMIT %s
            """,
            (job_id, limit),
        )
        return [dict(row) for row in cursor.fetchall()]


PRODUCT_VALIDATION_QUERY = """
    SELECT p.product_id, p.sku, nf.ingredients_text, nf.energy_kcal,
           nf.energy_kj, nf.fat_total, nf.fat_saturated, nf.carbs_total,
           nf.carbs_sugars, nf.protein, nf.salt, nf.fiber
    FROM products p
    LEFT JOIN nutritionfacts nf ON nf.product_id = p.product_id
    WHERE p.product_id = %s
"""


def validate_product(connection, product_id: int, validator=None) -> dict[str, Any]:
    """Revalidate one product and replace its report row only on success."""
    validator = validator or NutritionValidator()
    with connection.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(PRODUCT_VALIDATION_QUERY, (product_id,))
        product = cursor.fetchone()
        if not product:
            raise ValueError(f"Product {product_id} no longer exists")

        cursor.execute(INGREDIENT_BATCH_QUERY, ([product["sku"]],))
        ingredients = cursor.fetchall()
        result = validator.validate(
            enrich_mapped_ingredients(ingredients, product.get("ingredients_text")),
            product,
        )
        cursor.execute(
            UPSERT_QUERY,
            (
                product_id,
                result["suspicion_level"],
                result["suspicion_score"],
                Json(result["reasons"]),
            ),
        )
    connection.commit()
    return result