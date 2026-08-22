"""Focused tests for the Nutri-Score category type seeding rules."""

import os
import unittest
from unittest.mock import MagicMock, patch

from seed_nutriscore_category_types import (
    TYPE_SETS,
    build_source_mapping,
    category_type_for_code,
    get_database_url,
    seed,
)


class SeedNutriscoreCategoryTypesTests(unittest.TestCase):
    def test_source_sets_have_no_overlapping_codes(self):
        mapping = build_source_mapping()
        self.assertEqual(len(mapping), sum(len(codes) for codes in TYPE_SETS.values()))

    def test_calculator_full_fvn_prefixes_are_included(self):
        mapping = build_source_mapping()
        self.assertEqual(category_type_for_code("SH-2-1", mapping), "full_fvn")
        self.assertEqual(category_type_for_code("SH-2-1-999", mapping), "full_fvn")
        self.assertEqual(category_type_for_code("SH-2-2-999", mapping), "full_fvn")

    def test_explicit_sets_take_precedence_and_unknown_is_general(self):
        mapping = build_source_mapping()
        self.assertEqual(category_type_for_code("SH-5-3", mapping), "beverage")
        self.assertEqual(category_type_for_code("SH-11-9-25", mapping), "cheese")
        self.assertEqual(category_type_for_code("SH-99-99", mapping), "general")
        self.assertEqual(category_type_for_code(None, mapping), "general")

    def test_dev_prefers_neon_database_url(self):
        with patch.dict(
            os.environ,
            {"NEON_DATABASE_URL": "neon-url", "DATABASE_URL": "legacy-url"},
            clear=False,
        ):
            self.assertEqual(get_database_url("dev"), "neon-url")

    def test_dev_accepts_database_url_compatibility_fallback(self):
        with patch.dict(
            os.environ,
            {"NEON_DATABASE_URL": "", "DATABASE_URL": "legacy-url"},
            clear=False,
        ):
            self.assertEqual(get_database_url("dev"), "legacy-url")

    def test_missing_prod_url_fails_clearly(self):
        with patch.dict(os.environ, {"PROD_DATABASE_URL": ""}, clear=False):
            with self.assertRaisesRegex(RuntimeError, "PROD_DATABASE_URL"):
                get_database_url("prod")

    def test_seed_assigns_every_mixed_category_explicitly(self):
        """Exercise the DB path without connecting to a real database."""
        cursor = MagicMock()
        cursor.__enter__.return_value = cursor
        cursor.fetchall.side_effect = [
            [
                (1, "SH-2-1"),
                (2, "SH-5-3"),
                (3, None),
                (4, "SH-99-99"),
            ],
            [
                ("full_fvn", 1),
                ("beverage", 1),
                ("general", 2),
            ],
        ]
        cursor.fetchone.return_value = (0,)

        conn = MagicMock()
        conn.__enter__.return_value = conn
        conn.cursor.return_value = cursor

        with patch(
            "seed_nutriscore_category_types.get_database_url",
            return_value="test-database-url",
        ), patch(
            "seed_nutriscore_category_types.psycopg2.connect",
            return_value=conn,
        ):
            seed("dev")

        # The connection context is the atomic transaction boundary.
        conn.__enter__.assert_called_once()
        update_calls = [
            call
            for call in cursor.execute.call_args_list
            if "WHERE category_id = %s" in call.args[0]
        ]
        self.assertEqual(
            [call.args[1] for call in update_calls],
            [
                ("full_fvn", 1),
                ("beverage", 2),
                ("general", 3),
                ("general", 4),
            ],
        )
        conn.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()