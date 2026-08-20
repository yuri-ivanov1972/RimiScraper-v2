#!/usr/bin/env python3
"""
Initialize an empty Rimi scraper PostgreSQL database from schema.sql.

Usage:
    python init_database.py

The database connection must be supplied through DATABASE_URL. The script
creates schema objects only; it never imports product, category, or price data.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import psycopg2
from psycopg2 import Error as PsycopgError


SCHEMA_PATH = Path(__file__).with_name("schema.sql")

EXPECTED_TABLES = {
    "normalized_categories",
    "products",
    "nutritionfacts",
    "product_price_history",
    "productphotos",
    "ingredient_analysis",
    "ingredient_product_mapping",
    "category_processing_jobs",
    "processing_workers",
    "job_events",
    "product_processing_log",
    "update_statistics",
    "daily_update_logs",
}

REQUIRED_PRODUCT_COLUMNS = {
    "product_id",
    "sku",
    "name",
    "category_id",
    "nova_score",
    "nova_source",
    "is_hidden",
}


class DatabaseBootstrapError(RuntimeError):
    """Raised when the target database cannot be safely initialized."""


def get_database_url() -> str:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise DatabaseBootstrapError(
            "DATABASE_URL is not set. Add your PostgreSQL connection as a "
            "project secret, then run this command again."
        )
    return database_url


def read_schema() -> str:
    try:
        return SCHEMA_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        raise DatabaseBootstrapError(
            f"Could not read the schema file at {SCHEMA_PATH.name}."
        ) from exc


def existing_app_tables(cursor) -> set[str]:
    cursor.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = current_schema()
          AND table_type = 'BASE TABLE'
          AND table_name = ANY(%s)
        """,
        (list(EXPECTED_TABLES),),
    )
    return {row[0] for row in cursor.fetchall()}


def require_utf8_database(cursor) -> None:
    """Ensure the database can store Latvian and Estonian product text."""
    cursor.execute("SHOW server_encoding")
    server_encoding = cursor.fetchone()[0].upper()
    if server_encoding != "UTF8":
        raise DatabaseBootstrapError(
            f"The target database uses {server_encoding} encoding. Create a UTF-8 "
            "PostgreSQL database before running this initializer."
        )


def verify_schema(cursor) -> tuple[int, str]:
    tables = existing_app_tables(cursor)
    missing_tables = EXPECTED_TABLES - tables
    if missing_tables:
        missing = ", ".join(sorted(missing_tables))
        raise DatabaseBootstrapError(f"Schema verification failed; missing tables: {missing}.")

    cursor.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'products'
        """
    )
    product_columns = {row[0] for row in cursor.fetchall()}
    missing_columns = REQUIRED_PRODUCT_COLUMNS - product_columns
    if missing_columns:
        missing = ", ".join(sorted(missing_columns))
        raise DatabaseBootstrapError(
            f"Schema verification failed; products is missing columns: {missing}."
        )

    cursor.execute(
        """
        SELECT matviewname
        FROM pg_matviews
        WHERE schemaname = current_schema()
          AND matviewname = 'product_ingredient_cards'
        """
    )
    if cursor.fetchone() is None:
        raise DatabaseBootstrapError(
            "Schema verification failed; product_ingredient_cards was not created."
        )

    return len(tables), "product_ingredient_cards"


def initialize_database() -> None:
    database_url = get_database_url()
    schema_sql = read_schema()

    try:
        with psycopg2.connect(database_url) as connection:
            with connection.cursor() as cursor:
                require_utf8_database(cursor)
                existing_tables = existing_app_tables(cursor)
                if existing_tables and existing_tables != EXPECTED_TABLES:
                    found = ", ".join(sorted(existing_tables))
                    raise DatabaseBootstrapError(
                        "The database contains a partial Rimi scraper schema "
                        f"({found}). Refusing to modify it automatically. "
                        "Use an empty database or complete the migration first."
                    )

                cursor.execute(schema_sql)
                table_count, materialized_view = verify_schema(cursor)

        print("Database schema initialized successfully.")
        print(f"Verified {table_count} application tables and {materialized_view}.")
        print("No product, category, price, or other source data was imported.")
    except DatabaseBootstrapError:
        raise
    except (PsycopgError, UnicodeError) as exc:
        raise DatabaseBootstrapError(
            "Database setup failed. Check that DATABASE_URL points to a reachable "
            "PostgreSQL database and that its user can create extensions, tables, "
            "indexes, and materialized views."
        ) from exc


def main() -> int:
    try:
        initialize_database()
    except DatabaseBootstrapError as exc:
        print(f"Database initialization failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())