#!/usr/bin/env python3
"""Focused tests for rule-based ingredient/nutrition validation."""

import unittest
from unittest.mock import patch

from nutrition_validation_backfill import (
    get_database_url,
    main as backfill_main,
    validate_existing_products,
)
from nutrition_validator import (
    NutritionValidator,
    enrich_mapped_ingredients,
    normalize_ingredient_text,
    summarize_validation_results,
)


class NutritionValidatorTests(unittest.TestCase):
    def setUp(self):
        self.validator = NutritionValidator()

    def validate(self, ingredients, **nutrition):
        return self.validator.validate(ingredients, nutrition)

    @staticmethod
    def rules(result):
        return {reason["rule"] for reason in result["reasons"]}

    def assert_rule(self, rule, ingredients=(), **nutrition):
        result = self.validate(ingredients, **nutrition)
        self.assertIn(rule, self.rules(result), result)
        return result

    def test_latvian_normalization_and_term_boundaries(self):
        self.assertEqual(normalize_ingredient_text("  SĀLS),  "), "sāls")
        result = self.validate(["sālsskābe"], salt=0)
        self.assertNotIn("salt_present_but_salt_zero", self.rules(result))

    def test_dairy_with_zero_saturated_fat(self):
        result = self.assert_rule(
            "milk_present_but_saturated_fat_zero",
            ["pasterizēts piens", "saldais krējums"],
            fat_saturated=0,
        )
        finding = next(
            reason for reason in result["reasons"]
            if reason["rule"] == "milk_present_but_saturated_fat_zero"
        )
        self.assertEqual(finding["score"], 8)
        self.assertEqual(len(finding["ingredient_evidence"]), 2)

    def test_skimmed_milk_is_not_automatically_flagged(self):
        result = self.validate(
            ["vājpiena pulveris"],
            fat_total=0.1,
            fat_saturated=0.0,
        )
        self.assertNotIn(
            "milk_present_but_saturated_fat_zero",
            self.rules(result),
        )

    def test_fat_or_oil_with_zero_total_fat(self):
        self.assertEqual(
            self.validate(["saulespuķu eļļa"], fat_total=0)["reasons"],
            [],
        )

    def test_fat_rich_ingredient_with_zero_saturated_fat(self):
        self.assertEqual(
            self.validate(["kokosriekstu eļļa"], fat_saturated=0)["reasons"],
            [],
        )

    def test_sugar_with_zero_sugars(self):
        result = self.assert_rule(
            "sugar_ingredient_present_but_sugars_zero",
            ["glikozes-fruktozes sīrups"],
            carbs_sugars=0,
        )
        self.assertEqual(result["suspicion_score"], 8)
        self.assertEqual(result["suspicion_level"], "medium")

    def test_nonzero_sugars_are_not_flagged(self):
        result = self.validate(["cukurs"], carbs_sugars=0.1)
        self.assertNotIn(
            "sugar_ingredient_present_but_sugars_zero",
            self.rules(result),
        )

    def test_carbohydrate_ingredient_with_zero_carbohydrates(self):
        self.assertEqual(
            self.validate(["kviešu milti"], carbs_total=0)["reasons"],
            [],
        )

    def test_fruit_with_zero_sugars(self):
        self.assertEqual(
            self.validate(["zemeņu biezenis"], carbs_sugars=0)["reasons"],
            [],
        )

    def test_salt_with_zero_salt(self):
        self.assert_rule(
            "salt_present_but_salt_zero",
            ["jūras sāls"],
            salt=0,
        )

    def test_salty_ingredient_with_low_salt(self):
        self.assertEqual(
            self.validate(["sojas mērce"], salt=0.05)["reasons"],
            [],
        )

    def test_protein_ingredient_with_zero_protein(self):
        self.assertEqual(
            self.validate(["vistas gaļa"], protein=0)["reasons"],
            [],
        )

    def test_nuts_or_seeds_with_zero_fat(self):
        self.assertEqual(
            self.validate(["saulespuķu sēklas"], fat_total=0)["reasons"],
            [],
        )

    def test_cocoa_checks_each_zero_field(self):
        result = self.validate(
            ["kakao pulveris"],
            fat_total=0,
            fat_saturated=0,
            carbs_sugars=0,
        )
        self.assertEqual(result["reasons"], [])

    def test_saturated_fat_cannot_exceed_total_fat(self):
        self.assertEqual(
            self.validate([], fat_total=5, fat_saturated=8)["reasons"],
            [],
        )

    def test_sugars_cannot_exceed_carbohydrates(self):
        self.assertEqual(
            self.validate([], carbs_total=10, carbs_sugars=15)["reasons"],
            [],
        )

    def test_energy_inconsistency_uses_configured_tolerance(self):
        result = self.validate(
            [],
            energy_kcal=400,
            fat_total=10,
            carbs_total=10,
            protein=10,
        )
        self.assertEqual(result["reasons"], [])

    def test_energy_rounding_difference_is_not_flagged(self):
        result = self.validate(
            [],
            energy_kcal=175,
            fat_total=10,
            carbs_total=10,
            protein=10,
        )
        self.assertNotIn(
            "energy_inconsistent_with_macronutrients",
            self.rules(result),
        )

    def test_zero_value_cluster_adds_one_reason(self):
        result = self.validate(
            ["kviešu milti", "vistas gaļa", "saulespuķu eļļa"],
            fat_total=0,
            carbs_total=0,
            protein=0,
        )
        self.assertEqual(result["reasons"], [])

    def test_advisory_and_tiny_quantity_are_not_definite_evidence(self):
        advisory = self.validate(["var saturēt pienu"], fat_saturated=0)
        tiny = self.validate(
            [{"ingredient": "cukurs", "percentage": 0.5}],
            carbs_sugars=0,
        )
        self.assertEqual(advisory["reasons"], [])
        self.assertEqual(tiny["reasons"], [])

    def test_raw_label_only_enriches_parsed_mapping_confidence(self):
        tiny = enrich_mapped_ingredients(
            [{"ingredient": "cukurs"}],
            "Sastāvdaļas: cukurs (0,5%), ūdens",
        )
        advisory = enrich_mapped_ingredients(
            [{"ingredient": "var saturēt pienu"}],
            "Var saturēt pienu un riekstus.",
        )
        self.assertEqual(tiny[0]["percentage"], 0.5)
        self.assertTrue(advisory[0]["weak"])
        self.assertEqual(
            self.validate(tiny, carbs_sugars=0)["reasons"],
            [],
        )
        self.assertEqual(
            self.validate(advisory, fat_saturated=0)["reasons"],
            [],
        )

    def test_advisory_clause_marks_split_latvian_and_english_items_only(self):
        latvian = enrich_mapped_ingredients(
            [
                {"ingredient": "var ietvert pienu"},
                {"ingredient": "riekstus"},
            ],
            "Var ietvert pienu un riekstus.",
        )
        english = enrich_mapped_ingredients(
            [
                {"ingredient": "may contain milk"},
                {"ingredient": "nuts"},
            ],
            "May contain milk and nuts.",
        )
        self.assertTrue(latvian[0]["weak"])
        self.assertTrue(latvian[1]["weak"])
        self.assertTrue(english[0]["weak"])
        self.assertTrue(english[1]["weak"])

    def test_definite_dairy_is_not_weakened_by_separate_advisory(self):
        enriched = enrich_mapped_ingredients(
            [
                {"ingredient": "piena pulveris"},
                {"ingredient": "var saturēt pienu"},
            ],
            "Sastāvdaļas: piena pulveris. Var saturēt pienu.",
        )
        self.assertNotIn("weak", enriched[0])
        self.assertTrue(enriched[1]["weak"])
        result = self.validate(enriched, fat_saturated=0)
        self.assertIn(
            "milk_present_but_saturated_fat_zero",
            self.rules(result),
        )

    def test_duplicate_ingredients_do_not_multiply_rule_score(self):
        result = self.validate(
            ["cukurs", "cukurs", "cukurs"],
            carbs_sugars=0,
        )
        matching = [
            reason for reason in result["reasons"]
            if reason["rule"] == "sugar_ingredient_present_but_sugars_zero"
        ]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0]["score"], 8)

    def test_missing_values_trigger_only_matching_approved_ingredients(self):
        result = self.validate(["cukurs", "sāls", "piens", "vistas gaļa"])
        self.assertEqual(self.rules(result), {
            "sugar_ingredient_present_but_sugars_zero",
            "salt_present_but_salt_zero",
            "milk_present_but_saturated_fat_zero",
        })

    def test_blank_values_trigger_approved_pairs(self):
        result = self.validate(
            ["cukurs", "sāls", "piens"],
            carbs_sugars="",
            salt=" ",
            fat_saturated="",
        )
        self.assertEqual(len(result["reasons"]), 3)

    def test_any_one_approved_pair_is_sufficient(self):
        cases = [
            (["cukurs"], {"carbs_sugars": None}, "sugar_ingredient_present_but_sugars_zero"),
            (["sāls"], {"salt": None}, "salt_present_but_salt_zero"),
            (["piens"], {"fat_saturated": None}, "milk_present_but_saturated_fat_zero"),
        ]
        for ingredients, nutrition, expected_rule in cases:
            with self.subTest(expected_rule=expected_rule):
                result = self.validate(ingredients, **nutrition)
                self.assertEqual(self.rules(result), {expected_rule})
                self.assertGreater(result["suspicion_score"], 0)

    def test_positive_matching_values_prevent_all_three_flags(self):
        result = self.validate(
            ["cukurs", "sāls", "piens"],
            carbs_sugars=0.1,
            salt=0.01,
            fat_saturated=0.1,
        )
        self.assertEqual(result["reasons"], [])

    def test_summary_counts_levels_rules_and_percentages(self):
        suspicious = self.validate(["cukurs"], carbs_sugars=0)
        clean = self.validate(["ūdens"], carbs_sugars=0)
        summary = summarize_validation_results([suspicious, clean])
        self.assertEqual(summary["products_checked"], 2)
        self.assertEqual(summary["levels"]["medium"], 1)
        self.assertEqual(summary["levels"]["none"], 1)
        self.assertEqual(
            summary["rule_percentages"]["sugar_ingredient_present_but_sugars_zero"],
            50.0,
        )


class FakeCursor:
    def __init__(self, connection):
        self.connection = connection
        self.rows = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, query, params=None):
        normalized = " ".join(query.split())
        if "FROM products p LEFT JOIN nutritionfacts" in normalized:
            last_id, limit = params
            self.rows = [
                row for row in self.connection.products
                if row["product_id"] > last_id
            ][:limit]
        elif "FROM ingredient_product_mapping" in normalized:
            skus = set(params[0])
            self.rows = [
                row for row in self.connection.ingredients
                if row["product_sku"] in skus
            ]
        elif normalized.startswith("INSERT INTO nutrition_validation"):
            product_id, level, score, reasons = params
            self.connection.validation_rows[product_id] = {
                "suspicion_level": level,
                "suspicion_score": score,
                "reasons": reasons,
            }
            self.rows = []
        elif normalized.startswith(("SAVEPOINT", "RELEASE", "ROLLBACK TO")):
            self.rows = []
        else:
            raise AssertionError(f"Unexpected query: {normalized}")

    def fetchall(self):
        return list(self.rows)


class FakeConnection:
    def __init__(self):
        self.products = [{
            "product_id": 1,
            "sku": "SKU-1",
            "ingredients_text": "cukurs",
            "energy_kcal": None,
            "energy_kj": None,
            "fat_total": None,
            "fat_saturated": None,
            "carbs_total": 10,
            "carbs_sugars": 0,
            "protein": None,
            "salt": None,
            "fiber": None,
        }]
        self.ingredients = [{
            "product_sku": "SKU-1",
            "ingredient": "cukurs",
            "clean_name": None,
        }]
        self.validation_rows = {}
        self.commits = 0

    def cursor(self, cursor_factory=None):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1


class BackfillTests(unittest.TestCase):
    def test_production_backfill_requires_explicit_confirmation(self):
        with patch.dict(
            "os.environ",
            {"PROD_DATABASE_URL": "prod-db"},
            clear=True,
        ):
            with self.assertRaisesRegex(ValueError, "confirm-production"):
                get_database_url(production=True)

    def test_production_backfill_rejects_same_database_url(self):
        with patch.dict(
            "os.environ",
            {
                "DATABASE_URL": "same-db",
                "PROD_DATABASE_URL": "same-db",
            },
            clear=True,
        ):
            with self.assertRaisesRegex(ValueError, "must be different"):
                get_database_url(
                    production=True,
                    confirm_production=True,
                )

    def test_production_backfill_requires_production_url(self):
        with patch.dict(
            "os.environ",
            {"DATABASE_URL": "dev-db"},
            clear=True,
        ):
            with self.assertRaisesRegex(ValueError, "PROD_DATABASE_URL"):
                get_database_url(
                    production=True,
                    confirm_production=True,
                )

    def test_development_backfill_does_not_accept_production_confirmation(self):
        with patch.dict(
            "os.environ",
            {"DATABASE_URL": "dev-db"},
            clear=True,
        ):
            with self.assertRaisesRegex(ValueError, "requires --production"):
                get_database_url(
                    production=False,
                    confirm_production=True,
                )

    def test_cli_guard_fails_before_connecting(self):
        with patch.dict(
            "os.environ",
            {"PROD_DATABASE_URL": "prod-db"},
            clear=True,
        ):
            with patch(
                "nutrition_validation_backfill.psycopg2.connect"
            ) as connect:
                exit_code = backfill_main(["--production"])

        self.assertEqual(exit_code, 2)
        connect.assert_not_called()

    def test_backfill_upserts_one_current_result_on_repeated_runs(self):
        connection = FakeConnection()
        first = validate_existing_products(connection, batch_size=1)
        second = validate_existing_products(connection, batch_size=1)

        self.assertEqual(first["attempted"], 1)
        self.assertEqual(second["attempted"], 1)
        self.assertEqual(first["failures"], [])
        self.assertEqual(len(connection.validation_rows), 1)
        self.assertEqual(
            connection.validation_rows[1]["suspicion_level"],
            "medium",
        )
        self.assertEqual(connection.commits, 2)

    def test_backfill_resumes_after_last_committed_product_id(self):
        connection = FakeConnection()
        template = connection.products[0]
        connection.products = [
            {**template, "product_id": product_id, "sku": f"SKU-{product_id}"}
            for product_id in range(1, 4)
        ]
        connection.ingredients = [
            {
                "product_sku": f"SKU-{product_id}",
                "ingredient": "cukurs",
                "clean_name": None,
            }
            for product_id in range(1, 4)
        ]

        summary = validate_existing_products(
            connection,
            start_id=1,
            batch_size=1,
        )

        self.assertEqual(summary["attempted"], 2)
        self.assertEqual(summary["last_product_id"], 3)
        self.assertEqual(set(connection.validation_rows), {2, 3})

    def test_backfill_isolates_one_product_failure_and_continues(self):
        connection = FakeConnection()
        template = connection.products[0]
        connection.products = [
            {**template, "product_id": product_id, "sku": f"SKU-{product_id}"}
            for product_id in range(1, 4)
        ]

        class FlakyValidator:
            def validate(self, _ingredients, product):
                if product["product_id"] == 2:
                    raise RuntimeError("test failure")
                return {
                    "suspicion_level": "none",
                    "suspicion_score": 0,
                    "reasons": [],
                }

        summary = validate_existing_products(
            connection,
            batch_size=3,
            validator=FlakyValidator(),
        )

        self.assertEqual(summary["attempted"], 3)
        self.assertEqual(
            summary["failures"],
            [{
                "product_id": 2,
                "sku": "SKU-2",
                "error": "test failure",
            }],
        )
        self.assertEqual(set(connection.validation_rows), {1, 3})


if __name__ == "__main__":
    unittest.main()