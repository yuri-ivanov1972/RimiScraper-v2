"""Grade boundaries use real nutrient inputs, not mocked numeric scores."""

import pytest

from nutriscore_calculator import (
    NutriscoreCalculator, calculate_nutriscore, calculate_nutriscore_2024,
)
from test_nutriscore_category_types import FakeConnection


def nutrients(score):
    return dict(
        energy_kj=0, sugars_g=0, sat_fat_g=0,
        salt_g=0 if score < 1 else score * 0.2 + 0.01,
        protein_g=3 if score == -1 else 0,
    )


@pytest.mark.parametrize("category", ["general", "cheese", "red_meat"])
@pytest.mark.parametrize(
    "score,grade", [(-1, "A"), (0, "A"), (1, "B"), (2, "B"),
                    (3, "C"), (10, "C"), (11, "D"), (18, "D"), (19, "E")],
)
def test_standard_food_boundaries(category, score, grade):
    result = calculate_nutriscore_2024(category, **nutrients(score))
    assert (result["score"], result["grade"]) == (score, grade)
    assert result["n_points"] - result["p_points"] == score


@pytest.mark.parametrize("category_type", [
    "general", "cheese", "red_meat", "full_fvn", "half_fvn", None,
])
def test_zero_score_through_table_backed_single_and_batch(category_type):
    calculator = NutriscoreCalculator(FakeConnection({1: category_type}))
    values = dict(energy_kj=0, sugars=0, saturated_fat=0, salt=0,
                  protein=0, fruits_veg_nuts=0, category_id=1)
    for result in (
        calculator.calculate_single_product(**values),
        calculator.batch_calculate([values])[0],
    ):
        assert result["success"], result
        assert (result["score"], result["grade"]) == (0, "A")


def test_legacy_wrapper_uses_corrected_zero_boundary():
    score, grade, _ = calculate_nutriscore(0, 0, 0, 0, 0)
    assert (score, grade) == (0, "A")


@pytest.mark.parametrize("energy,score,grade", [
    (0, 0, "A"), (1, 0, "B"), (91, 2, "B"), (151, 3, "C"),
    (271, 6, "C"), (301, 7, "D"), (361, 9, "D"), (391, 10, "E"),
])
def test_beverage_boundaries_unchanged(energy, score, grade):
    result = calculate_nutriscore_2024("beverage", energy, 0, 0, 0, 0)
    assert (result["score"], result["grade"]) == (score, grade)


@pytest.mark.parametrize("protein,fiber,sugar,score,grade", [
    (3, 8, 0, -6, "A"), (0, 8, 0, -5, "B"), (0, 0, 0, 0, "B"),
    (0, 0, 7, 2, "B"), (0, 0, 11, 3, "C"),
])
def test_fats_oils_nuts_boundaries_unchanged(protein, fiber, sugar, score, grade):
    result = calculate_nutriscore_2024(
        "fats_oils_nuts", 0, sugar, 0, 0, protein, fiber, total_fat_g=20,
    )
    assert (result["score"], result["grade"]) == (score, grade)
