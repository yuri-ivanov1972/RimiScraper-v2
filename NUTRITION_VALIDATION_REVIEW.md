# Nutrition Validation Development Review

Review date: 2026-08-29

## Decision

The development schema in `migrations/004_add_nutrition_validation.sql` and
`schema.sql` is approved for Replit’s publish-time production schema migration.

This approval covers the `nutrition_validation` table, indexes, and reporting
views. It does not enable a production backfill or automatic validation after
scraping.

The application startup does not mutate production schema. Publishing applies
the schema diff, and the separately guarded backfill populates validation rows
after the schema is available.

Replit documents this publish-time schema synchronization at:
https://docs.replit.com/features/data-and-storage/development-and-production

## Production rollout

The guarded production backfill completed on 2026-08-29. The first process
committed 2,500 products before the execution tool timed out. It was resumed
from product ID 2,500 and completed the remaining 8,125 products with zero
product-level failures.

Read-only production verification after completion:

| Check | Result |
| --- | ---: |
| Products | 10,625 |
| Validation rows | 10,625 |
| Missing validation rows | 0 |
| Duplicate product IDs | 0 |
| Suspicious results | 898 |
| None | 9,727 |
| Low | 92 |
| Medium | 600 |
| High | 206 |

The production deployment was active and had a successful VM build when these
counts were verified. Its password visibility prevents unauthenticated visual
inspection, while the report's production backing views and row coverage were
verified directly.

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