#!/usr/bin/env python3
"""
Validate existing development products without scraping Rimi again.

Usage:
    python nutrition_validation_backfill.py
    python nutrition_validation_backfill.py --limit 100 --batch-size 25
    python nutrition_validation_backfill.py --start-id 1000

This command intentionally uses DATABASE_URL only.  Production rollout is a
separate reviewed step.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from typing import Any, Callable, Mapping

import psycopg2
from psycopg2.extras import Json, RealDictCursor

from nutrition_validator import (
    NutritionValidator,
    enrich_mapped_ingredients,
    summarize_validation_results,
)


PRODUCT_BATCH_QUERY = """
    SELECT
        p.product_id,
        p.sku,
        nf.ingredients_text,
        nf.energy_kcal,
        nf.energy_kj,
        nf.fat_total,
        nf.fat_saturated,
        nf.carbs_total,
        nf.carbs_sugars,
        nf.protein,
        nf.salt,
        nf.fiber
    FROM products p
    LEFT JOIN nutritionfacts nf ON nf.product_id = p.product_id
    WHERE p.product_id > %s
    ORDER BY p.product_id
    LIMIT %s
"""

INGREDIENT_BATCH_QUERY = """
    SELECT
        ipm.product_sku,
        ia.ingredient,
        ia.clean_name
    FROM ingredient_product_mapping ipm
    JOIN ingredient_analysis ia ON ia.id = ipm.ingredient_id
    WHERE ipm.product_sku = ANY(%s)
    ORDER BY ipm.product_sku, ia.id
"""

UPSERT_QUERY = """
    INSERT INTO nutrition_validation (
        product_id,
        suspicion_level,
        suspicion_score,
        reasons,
        checked_at
    )
    VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
    ON CONFLICT (product_id) DO UPDATE SET
        suspicion_level = EXCLUDED.suspicion_level,
        suspicion_score = EXCLUDED.suspicion_score,
        reasons = EXCLUDED.reasons,
        checked_at = EXCLUDED.checked_at
"""


def _load_ingredients(cursor, skus: list[str]) -> dict[str, list[dict[str, Any]]]:
    by_sku: dict[str, list[dict[str, Any]]] = defaultdict(list)
    if not skus:
        return by_sku
    cursor.execute(INGREDIENT_BATCH_QUERY, (skus,))
    for row in cursor.fetchall():
        # The original parser-normalized Latvian name is authoritative.  The
        # AI clean_name is retained only as context for future tuning.
        by_sku[row["product_sku"]].append({
            "ingredient": row["ingredient"],
            "clean_name": row.get("clean_name"),
        })
    return by_sku


def validate_existing_products(
    connection,
    *,
    limit: int | None = None,
    batch_size: int = 100,
    start_id: int = 0,
    status_callback: Callable[[str], None] | None = None,
    validator: NutritionValidator | None = None,
) -> dict[str, Any]:
    """
    Validate and upsert existing products in stable product_id order.

    Commits once per batch.  A bad product is isolated with a savepoint so it
    does not discard successful products from the same batch.
    """
    if limit is not None and limit < 1:
        raise ValueError("limit must be at least 1")
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")
    if start_id < 0:
        raise ValueError("start_id cannot be negative")

    status = status_callback or (lambda _message: None)
    validator = validator or NutritionValidator()
    last_id = start_id
    processed = 0
    failures: list[dict[str, Any]] = []
    validation_results: list[Mapping[str, Any]] = []

    with connection.cursor(cursor_factory=RealDictCursor) as cursor:
        while limit is None or processed < limit:
            remaining = batch_size if limit is None else min(batch_size, limit - processed)
            cursor.execute(PRODUCT_BATCH_QUERY, (last_id, remaining))
            products = cursor.fetchall()
            if not products:
                break

            ingredients_by_sku = _load_ingredients(
                cursor,
                [row["sku"] for row in products],
            )
            for row in products:
                product_id = row["product_id"]
                last_id = product_id
                cursor.execute("SAVEPOINT nutrition_validation_product")
                try:
                    result = validator.validate(
                        enrich_mapped_ingredients(
                            ingredients_by_sku.get(row["sku"], []),
                            row.get("ingredients_text"),
                        ),
                        row,
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
                    cursor.execute("RELEASE SAVEPOINT nutrition_validation_product")
                    validation_results.append(result)
                except Exception as exc:
                    cursor.execute("ROLLBACK TO SAVEPOINT nutrition_validation_product")
                    cursor.execute("RELEASE SAVEPOINT nutrition_validation_product")
                    failures.append({
                        "product_id": product_id,
                        "sku": row["sku"],
                        "error": str(exc),
                    })
                processed += 1

            connection.commit()
            status(
                f"Validated {processed} products "
                f"(last product_id={last_id}, failures={len(failures)})"
            )

    summary = summarize_validation_results(validation_results)
    summary["attempted"] = processed
    summary["failures"] = failures
    summary["start_id"] = start_id
    summary["last_product_id"] = last_id
    return summary


def fetch_suspicious_report(connection, limit: int = 20) -> list[dict[str, Any]]:
    """Return the database-only debug report, highest score first."""
    if limit < 1:
        return []
    with connection.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(
            """
            SELECT product_id, sku, product, suspicion_level,
                   suspicion_score, reasons, checked_at
            FROM nutrition_validation_report
            WHERE suspicion_score > 0
            ORDER BY suspicion_score DESC, product_id
            LIMIT %s
            """,
            (limit,),
        )
        return [dict(row) for row in cursor.fetchall()]


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate existing products in the development database."
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum products to validate (default: all after --start-id).",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Products committed per batch (default: 100).",
    )
    parser.add_argument(
        "--start-id",
        type=int,
        default=0,
        help="Validate products with product_id greater than this value.",
    )
    parser.add_argument(
        "--report-limit",
        type=int,
        default=10,
        help="Number of highest-scoring rows to include after the summary.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("DATABASE_URL is required for the development backfill.", file=sys.stderr)
        return 2

    connection = psycopg2.connect(database_url)
    try:
        summary = validate_existing_products(
            connection,
            limit=args.limit,
            batch_size=args.batch_size,
            start_id=args.start_id,
            status_callback=print,
        )
        report = fetch_suspicious_report(connection, args.report_limit)
        print("\nSummary:")
        print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
        if report:
            print("\nHighest-scoring products:")
            print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        return 1 if summary["failures"] else 0
    except psycopg2.errors.UndefinedTable:
        connection.rollback()
        print(
            "nutrition_validation is missing. Apply migrations/004_add_nutrition_validation.sql first.",
            file=sys.stderr,
        )
        return 2
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())