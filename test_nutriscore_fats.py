"""Updated fats/oils/nuts/seeds rules: official FAQ tables 7–8 (March 2025)."""

import pytest
from streamlit.testing.v1 import AppTest

from nutriscore_calculator import NutriscoreCalculator, calculate_nutriscore_2024
from test_nutriscore_category_types import FakeConnection


def fats(**overrides):
    values = dict(
        category="fats_oils_nuts", energy_kj=1000, sugars_g=0,
        sat_fat_g=0, salt_g=0, protein_g=20, fiber_g=4.2,
        fvl_pct=0, total_fat_g=100,
    )
    values.update(overrides)
    return calculate_nutriscore_2024(**values)


@pytest.mark.parametrize("negative", [6, 7, 8, 10, 11])
@pytest.mark.parametrize("fvl, fvl_points", [(0, 0), (90, 5)])
def test_protein_excluded_at_seven_even_with_five_fvl_points(negative, fvl, fvl_points):
    result = fats(salt_g=negative * 0.2 + 0.01, fvl_pct=fvl)
    included_protein = 7 if negative < 7 else 0
    assert result["n_points"] == negative
    assert result["components"]["protein_points"] == included_protein
    assert result["components"]["fiber_points"] == 2
    assert result["components"]["fvl_points"] == fvl_points
    assert result["p_points"] == included_protein + 2 + fvl_points
    assert result["components"]["positive_total"] == result["p_points"]
    assert result["score"] == negative - result["p_points"]
    if negative < 7:
        assert result["protein_status"] == "included"
    else:
        assert "blocked" in result["protein_status"]
        assert "7" in result["protein_status"]


@pytest.mark.parametrize("index,boundary", list(enumerate([10, 16, 22, 28, 34, 40, 46, 52, 58, 64])))
@pytest.mark.parametrize("offset", [-0.000001, 0, 0.000001])
def test_strict_saturated_fat_ratio_boundaries(index, boundary, offset):
    result = fats(sat_fat_g=boundary + offset)
    assert result["components"]["satfat_points"] == index + (offset >= 0)


@pytest.mark.parametrize("fat,saturates", [(25, 2.5), (50, 5), (100, 10)])
def test_ten_percent_ratio_is_one_point_at_different_fat_contents(fat, saturates):
    assert fats(total_fat_g=fat, sat_fat_g=saturates)["components"]["satfat_points"] == 1


@pytest.mark.parametrize("point", range(10))
@pytest.mark.parametrize("offset", [-0.000001, 0, 0.000001])
def test_energy_from_saturates_keeps_120_kj_intervals(point, offset):
    energy = 120 * (point + 1) + offset
    result = fats(sat_fat_g=energy / 37)
    assert result["components"]["energy_points"] == point + (offset > 0)
    # The declared total energy must not affect this category's energy points.
    assert fats(sat_fat_g=energy / 37, energy_kj=9000) == result


@pytest.mark.parametrize("negative", [6, 7, 8, 10, 11])
@pytest.mark.parametrize("fvl", [0, 90])
def test_single_and_batch_follow_corrected_fats_rules(negative, fvl):
    salt = negative * 0.2 + 0.01
    expected = fats(salt_g=salt, fvl_pct=fvl)
    calculator = NutriscoreCalculator(FakeConnection({1: "fat_oil_nut"}))
    values = dict(
        energy_kj=1000, sugars=0, saturated_fat=0, salt=salt, protein=20,
        fiber=4.2, total_fat=100, fruits_veg_nuts=fvl, category_id=1,
    )
    for result in (
        calculator.calculate_single_product(**values),
        calculator.batch_calculate([values])[0],
    ):
        assert result["success"], result
        for key in ("score", "grade", "n_points", "p_points", "components", "protein_status"):
            assert result[key] == expected[key]


@pytest.mark.parametrize("score,grade", [
    (-6, "A"), (-5, "B"), (2, "B"), (3, "C"), (10, "C"),
    (11, "D"), (18, "D"), (19, "E"),
])
def test_fats_grade_thresholds_preserved(score, grade):
    if score < 0:
        result = fats(protein_g=3 if score == -6 else 0, fiber_g=8)
    else:
        result = fats(protein_g=0, fiber_g=0, salt_g=score * 0.2 + 0.01)
    assert (result["score"], result["grade"]) == (score, grade)


@pytest.mark.parametrize("category", ["general", "cheese", "red_meat", "beverage"])
@pytest.mark.parametrize("negative", [6, 7, 8, 10, 11])
@pytest.mark.parametrize("fvl", [0, 90])
def test_other_categories_keep_existing_protein_behavior(category, negative, fvl):
    result = calculate_nutriscore_2024(
        category, 0, 0, 0, negative * 0.2 + 0.01, 20, 4.2, fvl,
    )
    # Preserve the separately scoped general-food FVL bypass, cheese exemption,
    # red-meat protein cap, and beverage rule.
    blocked = category in ("general", "red_meat") and negative >= 11 and fvl == 0
    assert ("blocked" in result["protein_status"]) == blocked
    raw_protein = 2 if category == "red_meat" else 7
    fiber = 2
    fvl_points = (6 if category == "beverage" else 5) if fvl else 0
    assert result["p_points"] == fiber + fvl_points + (0 if blocked else raw_protein)


@pytest.mark.parametrize("category,show_guidance", [("fat_oil_nut", True), ("general", False)])
def test_qualifying_oils_guidance_is_contextual(category, show_guidance):
    app = AppTest.from_string(
        "from types import SimpleNamespace\n"
        "from main import render_nutrition_edit_form\n"
        f"render_nutrition_edit_form(SimpleNamespace(), "
        f"{{'product_id': 1, 'nutriscore_category_type': '{category}'}})\n"
    ).run()
    assert not app.exception
    matching = [c.value for c in app.caption if "olīvu" in c.value]
    assert bool(matching) == show_guidance
    if show_guidance:
        assert "avokado" in matching[0] and "sojas" in matching[0]
        assert "vīnogu kauliņu" in matching[0].casefold() and "sēklas" in matching[0]
    # Guidance must not infer a percentage or change the nullable default.
    assert app.number_input(key="fvl_percentage_1").value is None
