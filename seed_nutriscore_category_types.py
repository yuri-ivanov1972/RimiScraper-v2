#!/usr/bin/env python3
"""
Seed normalized_categories.nutriscore_category_type from the calculator rules.

This command intentionally rebuilds every category assignment in one selected
database. It never updates Dev and Prod in the same run.

Usage:
    python seed_nutriscore_category_types.py --environment dev
    python seed_nutriscore_category_types.py --environment prod
    python seed_nutriscore_category_types.py --environment dev --dry-run

The database URLs are read from:
    dev  -> NEON_DATABASE_URL (DATABASE_URL is accepted as a compatibility fallback)
    prod -> PROD_DATABASE_URL
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from typing import Dict, Iterable, Mapping, Optional, Set

import psycopg2

from nutriscore_calculator import (
    BEVERAGE_CATEGORIES,
    CHEESE_CATEGORIES,
    FAT_OIL_NUT_CATEGORIES,
    FULL_FVN_CATEGORIES,
    HALF_FVN_CATEGORIES,
    RED_MEAT_CATEGORIES,
)


TYPE_SETS: Mapping[str, Set[str]] = {
    "beverage": BEVERAGE_CATEGORIES,
    "cheese": CHEESE_CATEGORIES,
    "red_meat": RED_MEAT_CATEGORIES,
    "fat_oil_nut": FAT_OIL_NUT_CATEGORIES,
    "full_fvn": FULL_FVN_CATEGORIES,
    "half_fvn": HALF_FVN_CATEGORIES,
}

# These prefixes are part of the calculator's FVN rule and cover category
# descendants that are not individually listed in FULL_FVN_CATEGORIES.
FULL_FVN_PREFIXES = ("SH-2-1", "SH-2-2")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Rebuild Nutri-Score category types for exactly one database. "
            "All categories not in a special calculator set become General."
        )
    )
    parser.add_argument(
        "--environment",
        choices=("dev", "prod"),
        required=True,
        help=(
            "Database to update: dev uses NEON_DATABASE_URL "
            "(DATABASE_URL fallback); prod uses PROD_DATABASE_URL."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and preview assignments without writing any data.",
    )
    return parser.parse_args()


def get_database_url(environment: str) -> str:
    variables = (
        ("NEON_DATABASE_URL", "DATABASE_URL")
        if environment == "dev"
        else ("PROD_DATABASE_URL",)
    )
    for variable in variables:
        database_url = os.environ.get(variable)
        if database_url:
            return database_url

    if environment == "dev":
        raise RuntimeError(
            "NEON_DATABASE_URL is not set (DATABASE_URL compatibility fallback "
            "is also unavailable); refusing to run without an explicit dev target."
        )
    raise RuntimeError(
        "PROD_DATABASE_URL is not set; refusing to run without an explicit prod target."
    )


def build_source_mapping() -> Dict[str, str]:
    """Build and validate the category-code-to-type mapping."""
    mapping: Dict[str, str] = {}
    duplicates: Dict[str, Set[str]] = {}

    for category_type, category_codes in TYPE_SETS.items():
        for raw_code in category_codes:
            code = raw_code.strip().upper()
            previous_type = mapping.get(code)
            if previous_type and previous_type != category_type:
                duplicates.setdefault(code, {previous_type}).add(category_type)
            else:
                mapping[code] = category_type

    if duplicates:
        duplicate_details = ", ".join(
            f"{code}: {', '.join(sorted(types))}"
            for code, types in sorted(duplicates.items())
        )
        raise ValueError(
            "A category appears in multiple Nutri-Score sets; refusing to update: "
            + duplicate_details
        )

    return mapping


def category_type_for_code(
    code: Optional[str], source_mapping: Mapping[str, str]
) -> str:
    """Return the stored type while matching the calculator's prefix rule."""
    if not code:
        return "general"
    code = code.strip().upper()
    if not code:
        return "general"
    if code in source_mapping:
        return source_mapping[code]
    if any(code.startswith(prefix) for prefix in FULL_FVN_PREFIXES):
        return "full_fvn"
    return "general"


def print_summary(
    environment: str,
    total_categories: int,
    assigned_counts: Counter[str],
    missing_codes: Iterable[str],
    changed_count: int,
    dry_run: bool,
) -> None:
    if dry_run:
        print(
            f"Dry-run: no data written; {changed_count} categories will change "
            f"in {environment}."
        )
    else:
        print(f"Updated {total_categories} categories in {environment}.")
    print("Assignments:")
    for category_type in ("general", *TYPE_SETS.keys()):
        print(f"  {category_type:12s} {assigned_counts.get(category_type, 0):>4}")

    missing = sorted(set(missing_codes))
    if missing:
        print(
            f"Warning: {len(missing)} source codes were not found in the selected database:"
        )
        for code in missing:
            print(f"  {code}")


def seed(environment: str, dry_run: bool = False) -> None:
    source_mapping = build_source_mapping()
    database_url = get_database_url(environment)

    conn = None
    try:
        conn = psycopg2.connect(database_url)
        with conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT category_id,
                           UPPER(TRIM(rimi_category_code)),
                           nutriscore_category_type,
                           nutriscore_category_type_explicit
                    FROM normalized_categories
                    ORDER BY category_id
                    """
                )
                categories = cursor.fetchall()
                if not categories:
                    raise RuntimeError(
                        "normalized_categories is empty; refusing to seed an empty schema."
                    )

                database_codes = {
                    category[1] for category in categories if category[1]
                }
                missing_codes = set(source_mapping) - database_codes
                planned_assignments = []
                changed_count = 0
                for category in categories:
                    category_id, code = category[:2]
                    category_type = category_type_for_code(code, source_mapping)
                    planned_assignments.append((category_id, category_type))

                    # The two optional fields make the comparison work with
                    # databases that predate the explicit assignment marker.
                    current_type = category[2] if len(category) > 2 else None
                    current_explicit = category[3] if len(category) > 3 else None
                    if current_type != category_type or current_explicit is not True:
                        changed_count += 1

                # Rebuild every assignment, including prefix-based Full FVN
                # descendants. This also removes any old manual assignments.
                if not dry_run:
                    for category_id, category_type in planned_assignments:
                        cursor.execute(
                            """
                            UPDATE normalized_categories
                            SET nutriscore_category_type = %s,
                                nutriscore_category_type_explicit = TRUE
                            WHERE category_id = %s
                            """,
                            (category_type, category_id),
                        )

                    cursor.execute(
                        """
                        SELECT nutriscore_category_type, COUNT(*)
                        FROM normalized_categories
                        GROUP BY nutriscore_category_type
                        """
                    )
                    assigned_counts = Counter(
                        {
                            category_type: count
                            for category_type, count in cursor.fetchall()
                        }
                    )

                    cursor.execute(
                        """
                        SELECT COUNT(*)
                        FROM normalized_categories
                        WHERE nutriscore_category_type IS NULL
                           OR nutriscore_category_type_explicit IS NOT TRUE
                        """
                    )
                    incomplete_count = cursor.fetchone()[0]
                    if incomplete_count:
                        raise RuntimeError(
                            f"Verification failed: {incomplete_count} categories are not fully assigned."
                        )
                else:
                    assigned_counts = Counter(
                        category_type for _, category_type in planned_assignments
                    )

                total_categories = len(categories)
                counted_categories = sum(assigned_counts.values())
                if counted_categories != total_categories:
                    raise RuntimeError(
                        "Verification failed: assignment counts do not match "
                        f"the category count ({counted_categories} != {total_categories})."
                    )

        print_summary(
            environment,
            total_categories,
            assigned_counts,
            missing_codes,
            changed_count,
            dry_run,
        )
    except Exception:
        if conn is not None:
            conn.rollback()
        raise
    finally:
        if conn is not None:
            conn.close()


def main() -> int:
    args = parse_args()
    try:
        seed(args.environment, dry_run=args.dry_run)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())