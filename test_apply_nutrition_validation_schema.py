#!/usr/bin/env python3
"""Tests for the schema-only nutrition-validation migration runner."""

import os
import unittest
from unittest.mock import patch

from apply_nutrition_validation_schema import (
    EXPECTED_COLUMNS,
    EXPECTED_INDEXES,
    EXPECTED_VIEWS,
    NutritionValidationMigrationError,
    get_database_url,
    read_migration,
    verify_schema,
)


class FakeCursor:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.rows = []

    def execute(self, _query, _params=None):
        self.rows = next(self.responses)

    def fetchall(self):
        return self.rows


class NutritionValidationSchemaMigrationTests(unittest.TestCase):
    def test_reads_idempotent_migration_004(self):
        sql = read_migration()
        self.assertIn(
            "CREATE TABLE IF NOT EXISTS nutrition_validation",
            sql,
        )
        self.assertIn(
            "CREATE OR REPLACE VIEW nutrition_validation_rule_summary",
            sql,
        )

    def test_production_target_requires_production_url(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(
                NutritionValidationMigrationError,
                "PROD_DATABASE_URL is not set",
            ):
                get_database_url(production=True)

    def test_verifies_all_required_schema_objects(self):
        cursor = FakeCursor([
            [(name,) for name in EXPECTED_COLUMNS],
            [(name,) for name in EXPECTED_INDEXES],
            [(name,) for name in EXPECTED_VIEWS],
        ])
        verify_schema(cursor)

    def test_reports_missing_schema_objects(self):
        cursor = FakeCursor([
            [(name,) for name in EXPECTED_COLUMNS - {"reasons"}],
            [(name,) for name in EXPECTED_INDEXES],
            [(name,) for name in EXPECTED_VIEWS],
        ])
        with self.assertRaisesRegex(
            NutritionValidationMigrationError,
            "columns: reasons",
        ):
            verify_schema(cursor)


if __name__ == "__main__":
    unittest.main()