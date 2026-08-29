# Nutrition Validation Development Review

Review date: 2026-08-29

## Decision

The development schema in `migrations/004_add_nutrition_validation.sql` and
`schema.sql` is approved for the Replit publish-time production migration run
by `combined_startup.sh`.

This approval covers the `nutrition_validation` table, indexes, and reporting
views. It does not enable a production backfill or automatic validation after
scraping.

At deployment startup,
`python apply_nutrition_validation_schema.py --production` applies migration
004 to `PROD_DATABASE_URL` and verifies every approved schema object before
Streamlit or the worker starts. Publishing fails explicitly if migration or
verification fails.

## Backfill coverage

Two complete development backfills were run against `DATABASE_URL`.

- Products checked: 3,014
- Nutrition rows: 3,014
- Ingredient mappings reviewed by the backfill: 36,546
- Product-level failures: 0
- Current validation rows after each run: 3,014

The second run produced the same level distribution, rule distribution, and
score ranges as the first run.

## Level distribution

| Level | Products | Percentage |
| --- | ---: | ---: |
| None | 2,701 | 89.62% |
| Low | 47 | 1.56% |
| Medium | 171 | 5.67% |
| High | 95 | 3.15% |

High scores ranged from 10 to 38. Medium scores ranged from 5 to 8.

## Rule distribution

| Rule | Products | Percentage |
| --- | ---: | ---: |
| `salt_present_but_salt_zero` | 166 | 5.51% |
| `sugar_ingredient_present_but_sugars_zero` | 94 | 3.12% |
| `fruit_present_but_sugars_zero` | 57 | 1.89% |
| `energy_inconsistent_with_macronutrients` | 39 | 1.29% |
| `milk_present_but_saturated_fat_zero` | 34 | 1.13% |
| `multiple_nutrition_values_inconsistent_with_ingredients` | 26 | 0.86% |
| `high_saturated_fat_ingredient_but_saturated_fat_zero` | 24 | 0.80% |
| `carbohydrate_ingredient_present_but_carbohydrates_zero` | 18 | 0.60% |
| `saturated_fat_exceeds_total_fat` | 16 | 0.53% |
| `sugars_exceed_carbohydrates` | 13 | 0.43% |
| `cocoa_or_chocolate_but_saturated_fat_zero` | 9 | 0.30% |
| `cocoa_or_chocolate_but_sugars_zero` | 9 | 0.30% |
| `fat_ingredient_present_but_fat_zero` | 8 | 0.27% |
| `protein_ingredient_present_but_protein_zero` | 5 | 0.17% |
| `salty_ingredient_but_low_salt` | 1 | 0.03% |

## Tuning review

No keyword, weight, or threshold changes were made.

Representative high findings contained explicit ingredient evidence paired
with declared zero values, multiple zero-value contradictions, or impossible
numeric relationships such as saturated fat exceeding total fat and sugars
exceeding carbohydrates. The most frequent medium findings similarly used
explicit salt or sugar evidence.

The review found isolated contextual or rounding cases, including “piena
oolong” and trace oil or sugar ingredients in products declaring zero. These
cases were too infrequent and varied to justify removing broad Latvian terms or
weakening thresholds. They remain explainable review findings rather than
automatic corrections.

The validator remains read-only with respect to source ingredient and nutrition
records.