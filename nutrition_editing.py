"""Atomic manual nutrition edits shared by the Products UI and regression tests."""

from nutriscore_calculator import NutriscoreCalculator, validate_fvl_percentage


NUTRIENT_FIELDS = (
    "energy_kj", "energy_kcal", "fat_total", "fat_saturated", "carbs_total",
    "carbs_sugars", "fiber", "protein", "salt",
)


def save_nutrition_edit(connection, product_id, values, percentage, manual_edit):
    """Save a nullable percentage override and its score in one transaction."""
    try:
        percentage = validate_fvl_percentage(percentage)
        with connection.cursor() as cur:
            cur.execute(
                """
                SELECT p.category_id, p.name, nf.ingredients_text
                FROM products p
                LEFT JOIN nutritionfacts nf ON nf.product_id = p.product_id
                WHERE p.product_id = %s
                FOR UPDATE OF p
                """,
                (product_id,),
            )
            product = cur.fetchone()
            if product is None:
                raise ValueError("Product not found")
            if isinstance(product, dict):
                category_id, name, ingredients = (
                    product["category_id"], product["name"], product["ingredients_text"]
                )
            else:
                category_id, name, ingredients = product
            result = NutriscoreCalculator(connection).calculate_single_product(
                energy_kj=values["energy_kj"],
                sugars=values["carbs_sugars"],
                saturated_fat=values["fat_saturated"],
                salt=values["salt"],
                protein=values["protein"],
                fiber=values["fiber"],
                total_fat=values["fat_total"],
                fruits_veg_nuts=percentage,
                category_id=category_id,
                product_name=name,
                ingredients_text=ingredients,
                # No product_id: clearing an override must not reload its old value.
            )
            if not result.get("success"):
                raise ValueError(result.get("error", "Nutri-Score calculation failed"))

            fields = (*NUTRIENT_FIELDS, "fruit_veg_legume_percent",
                      "nutri_score_grade", "nutri_score_points",
                      "nutrition_manual_edit", "is_fiber_correct")
            assignments = ", ".join(f"{field} = EXCLUDED.{field}" for field in fields)
            placeholders = ", ".join(["%s"] * (len(fields) + 1))
            cur.execute(
                f"""
                INSERT INTO nutritionfacts (product_id, {", ".join(fields)})
                VALUES ({placeholders})
                ON CONFLICT (product_id) DO UPDATE SET {assignments}
                """,
                (
                    product_id,
                    *(values[field] for field in NUTRIENT_FIELDS),
                    percentage, result["grade"], result["score"], manual_edit,
                    bool(values["fiber"] and values["fiber"] > 0),
                ),
            )
        connection.commit()
        return result
    except Exception:
        connection.rollback()
        raise
