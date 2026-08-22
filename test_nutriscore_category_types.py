"""Tests for table-backed Nutri-Score category classification."""

import unittest
from types import SimpleNamespace

from nutriscore_calculator import NutriscoreCalculator
from nutrition_enrichment_service import NutritionEnrichmentService


class FakeCursor:
    def __init__(self, rows, queries, fail=False):
        self.rows = rows
        self.queries = queries
        self.fail = fail
        self.category_id = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def execute(self, query, params):
        if self.fail:
            raise RuntimeError("database is unavailable")
        self.queries.append((query, params))
        self.category_id = params[0]

    def fetchone(self):
        category_type = self.rows.get(self.category_id)
        return None if self.category_id not in self.rows else (category_type,)


class FakeConnection:
    def __init__(self, rows=None, fail=False):
        self.rows = rows or {}
        self.queries = []
        self.fail = fail

    def cursor(self):
        return FakeCursor(self.rows, self.queries, self.fail)


class NutriscoreCategoryTypeTests(unittest.TestCase):
    def calculate(self, category_type, category_id=1, **overrides):
        connection = FakeConnection({category_id: category_type})
        calculator = NutriscoreCalculator(connection)
        values = {
            "energy_kj": 1000,
            "sugars": 5,
            "saturated_fat": 2,
            "salt": 0.4,
            "protein": 12,
            "fiber": 3,
            "total_fat": 20,
            "category_id": category_id,
        }
        values.update(overrides)
        return calculator.calculate_single_product(**values)

    def test_saved_types_map_to_scoring_category_and_fvn_percentage(self):
        expectations = {
            "general": ("general", 0.0),
            "beverage": ("beverage", 0.0),
            "cheese": ("cheese", 0.0),
            "red_meat": ("red_meat", 0.0),
            "fat_oil_nut": ("fats_oils_nuts", 0.0),
            "full_fvn": ("general", 100.0),
            "half_fvn": ("general", 50.0),
        }
        for saved_type, (scoring_category, fvn_percentage) in expectations.items():
            with self.subTest(saved_type=saved_type):
                result = self.calculate(saved_type)
                self.assertTrue(result["success"])
                self.assertEqual(
                    result["classification"]["nutriscore_category"], scoring_category
                )
                self.assertEqual(
                    result["classification"]["fruits_veg_nuts_percent"],
                    fvn_percentage,
                )

    def test_null_saved_type_uses_general_scoring(self):
        result = self.calculate(None)
        self.assertTrue(result["success"])
        self.assertEqual(result["classification"]["category_type"], "general")
        self.assertEqual(result["classification"]["nutriscore_category"], "general")

    def test_category_type_change_affects_subsequent_calculation(self):
        connection = FakeConnection({7: "general"})
        inputs = {
            "energy_kj": 1000,
            "sugars": 0,
            "saturated_fat": 0,
            "salt": 0,
            "protein": 25,
            "category_id": 7,
        }
        general_result = NutriscoreCalculator(connection).calculate_single_product(**inputs)
        connection.rows[7] = "red_meat"
        red_meat_result = NutriscoreCalculator(connection).calculate_single_product(**inputs)

        self.assertTrue(general_result["success"])
        self.assertTrue(red_meat_result["success"])
        self.assertNotEqual(general_result["score"], red_meat_result["score"])

    def test_lookup_is_cached_within_one_calculator(self):
        connection = FakeConnection({3: "cheese"})
        calculator = NutriscoreCalculator(connection)
        for _ in range(2):
            result = calculator.calculate_single_product(
                energy_kj=500,
                sugars=1,
                saturated_fat=2,
                salt=0.2,
                protein=10,
                category_id=3,
            )
            self.assertTrue(result["success"])
        self.assertEqual(len(connection.queries), 1)

    def test_missing_category_id_returns_clear_error(self):
        result = NutriscoreCalculator(FakeConnection({1: "general"})).calculate_single_product(
            energy_kj=500,
            sugars=1,
            saturated_fat=1,
            salt=0.2,
            protein=4,
        )
        self.assertFalse(result["success"])
        self.assertIn("category_id is required", result["error"])

    def test_unknown_category_returns_clear_error(self):
        result = NutriscoreCalculator(FakeConnection()).calculate_single_product(
            energy_kj=500,
            sugars=1,
            saturated_fat=1,
            salt=0.2,
            protein=4,
            category_id=404,
        )
        self.assertFalse(result["success"])
        self.assertIn("No normalized category exists", result["error"])

    def test_database_lookup_failure_returns_clear_error(self):
        result = NutriscoreCalculator(FakeConnection(fail=True)).calculate_single_product(
            energy_kj=500,
            sugars=1,
            saturated_fat=1,
            salt=0.2,
            protein=4,
            category_id=1,
        )
        self.assertFalse(result["success"])
        self.assertIn("Could not load Nutri-Score category type", result["error"])

    def test_enrichment_uses_saved_category_type(self):
        connection = FakeConnection({9: "red_meat"})
        service = object.__new__(NutritionEnrichmentService)
        service.status_callback = lambda _message: None
        nutrition = SimpleNamespace(
            energy_kj=1000,
            energy_kcal=None,
            carbs_sugars=0,
            fat_saturated=0,
            salt=0,
            protein=25,
            fiber=0,
            fat_total=10,
        )

        enrichment_score, enrichment_grade = service._calculate_nutriscore(
            connection=connection,
            nutrition=nutrition,
            category_id=9,
            product_name="Test meat",
        )
        expected = NutriscoreCalculator(FakeConnection({9: "red_meat"})).calculate_single_product(
            energy_kj=1000,
            sugars=0,
            saturated_fat=0,
            salt=0,
            protein=25,
            fiber=0,
            total_fat=10,
            product_name="Test meat",
            category_id=9,
        )

        self.assertTrue(expected["success"])
        self.assertEqual((enrichment_score, enrichment_grade), (expected["score"], expected["grade"]))


if __name__ == "__main__":
    unittest.main()