#!/usr/bin/env python3
"""
Export the normalized_categories table to a CSV file.

Usage:
    python export_categories.py
    python export_categories.py --output my_categories.csv

DATABASE_URL must be set as a project secret.
"""

import csv
import os
import sys
import argparse
from datetime import datetime

import psycopg2
from psycopg2.extras import RealDictCursor


def main() -> int:
    parser = argparse.ArgumentParser(description="Export normalized_categories to CSV")
    parser.add_argument(
        "--output",
        default=f"normalized_categories_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        help="Output file path (default: normalized_categories_YYYYMMDD_HHMMSS.csv)",
    )
    args = parser.parse_args()

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("Error: DATABASE_URL is not set.", file=sys.stderr)
        return 1

    try:
        with psycopg2.connect(database_url, cursor_factory=RealDictCursor) as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT
                        category_id,
                        rimi_category_code,
                        name_lv,
                        name_en,
                        parent_category_id,
                        level,
                        nova_score,
                        nova_score_explicit
                    FROM normalized_categories
                    ORDER BY level, rimi_category_code
                """)
                rows = cursor.fetchall()

        if not rows:
            print("Table normalized_categories is empty — nothing to export.")
            return 0

        with open(args.output, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)

        print(f"Exported {len(rows)} rows to {args.output}")
        return 0

    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
