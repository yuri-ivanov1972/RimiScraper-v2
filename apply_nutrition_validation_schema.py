#!/usr/bin/env python3
"""Apply and verify the additive nutrition-validation schema migration."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import psycopg2
from psycopg2 import Error as PsycopgError


MIGRATION_PATH = (
    Path(__file__).with_name("migrations")
    / "004_add_nutrition_validation.sql"
)
EXPECTED_COLUMNS = {
    "id",
    "product_id",
    "suspicion_level",
    "suspicion_score",
    "reasons",
    "checked_at",
}
EXPECTED_INDEXES = {
    "idx_nutrition_validation_score",
    "idx_nutrition_validation_level",
}
EXPECTED_VIEWS = {
    "nutrition_validation_report",
    "nutrition_validation_summary",
    "nutrition_validation_rule_summary",
}


class NutritionValidationMigrationError(RuntimeError):
    """Raised when migration 004 cannot be applied or verified."""


def get_database_url(*, production: bool) -> str:
    variable = "PROD_DATABASE_URL" if production else "DATABASE_URL"
    database_url = os.environ.get(variable)
    if not database_url:
        raise NutritionValidationMigrationError(f"{variable} is not set.")
    return database_url


def read_migration() -> str:
    try:
        return MIGRATION_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        raise NutritionValidationMigrationError(
            f"Could not read {MIGRATION_PATH}."
        ) from exc


def verify_schema(cursor) -> None:
    cursor.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'nutrition_validation'
        """
    )
    columns = {row[0] for row in cursor.fetchall()}

    cursor.execute(
        """
        SELECT indexname
        FROM pg_indexes
        WHERE schemaname = current_schema()
          AND tablename = 'nutrition_validation'
        """
    )
    indexes = {row[0] for row in cursor.fetchall()}

    cursor.execute(
        """
        SELECT table_name
        FROM information_schema.views
        WHERE table_schema = current_schema()
          AND table_name = ANY(%s)
        """,
        (sorted(EXPECTED_VIEWS),),
    )
    views = {row[0] for row in cursor.fetchall()}

    missing = []
    if EXPECTED_COLUMNS - columns:
        missing.append(
            "columns: " + ", ".join(sorted(EXPECTED_COLUMNS - columns))
        )
    if EXPECTED_INDEXES - indexes:
        missing.append(
            "indexes: " + ", ".join(sorted(EXPECTED_INDEXES - indexes))
        )
    if EXPECTED_VIEWS - views:
        missing.append(
            "views: " + ", ".join(sorted(EXPECTED_VIEWS - views))
        )
    if missing:
        raise NutritionValidationMigrationError(
            "Migration 004 verification failed; missing " + "; ".join(missing)
        )


def apply_migration(database_url: str) -> None:
    migration_sql = read_migration()
    try:
        with psycopg2.connect(database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(migration_sql)
                verify_schema(cursor)
    except NutritionValidationMigrationError:
        raise
    except PsycopgError as exc:
        raise NutritionValidationMigrationError(
            "Migration 004 failed. Confirm the target database already has "
            "the products table and permits schema changes."
        ) from exc


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Apply the nutrition-validation schema migration."
    )
    parser.add_argument(
        "--production",
        action="store_true",
        help="Use PROD_DATABASE_URL instead of development DATABASE_URL.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    target = "production" if args.production else "development"
    try:
        apply_migration(get_database_url(production=args.production))
    except NutritionValidationMigrationError as exc:
        print(
            f"Nutrition validation schema migration failed: {exc}",
            file=sys.stderr,
        )
        return 1

    print(
        "Nutrition validation schema migration applied and verified "
        f"for {target}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())