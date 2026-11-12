# Fruit, vegetable and legume percentage

In **Products → product details → edit nutrition**, enter a percentage between
0 and 100 (up to two decimal places) to save a manual override, including an
explicit 0%. Leave the field empty, or delete its contents and save, to use the
category default shown below the field. There is no separate default checkbox.
The normal save button recalculates Nutri-Score.

The override is independent of the general manual-nutrition checkbox. Scraping,
USDA enrichment and table-backed recalculations read it without overwriting it.
It counts fruit, vegetables and legumes, not nuts.

## Qualifying oils in the fats, oils, nuts and seeds category

For products assigned the saved `fat_oil_nut` category type, FVL also includes
qualifying oils derived from the **entire edible part** of an FVL ingredient,
such as olive, avocado and soybean oils. Grapeseed oil does not qualify. Nuts
and seeds do not count toward FVL merely because they belong to this category.
Enter the eligible share manually: no percentage is inferred from the product
name and no saved override or category default is changed automatically.

The updated category calculation excludes protein when negative points N are
**7 or more**, even with five FVL points. Saturates/total-fat ratio boundaries
are strict: exactly 10% earns one point and exactly 64% earns ten points.
Energy remains saturated fat (g/100g) × 37 kJ, with 120-kJ point intervals.
Category grades remain A ≤ −6, B −5–2, C 3–10, D 11–18, E ≥19.

Reference: [Santé publique France FAQ, 17 March 2025, updated algorithm,
tables 7–8](https://www.santepubliquefrance.fr/sites/default/files/rdd/document/FAQ-updatedAlgo-V11.pdf).
These code corrections do not bulk-recalculate stored scores. Existing grades
need a separately approved recalculation to reflect them.

## Schema rollout

Development has the nullable `nutritionfacts.fruit_veg_legume_percent` column
(NUMERIC(5,2), CHECK between 0 and 100). `schema.sql` includes it for new databases.
The guarded development-only post-merge setup adds it to existing development
databases idempotently; it refuses production targeting.
Existing databases need the same additive column before running this application
version. Existing rows remain NULL, preserving category defaults; no bulk
rescore or percentage backfill is required.

Production uses a separately configured database in this project. **No production
schema or product data was changed for this feature.** Obtain separate approval
to apply the additive column to that database before publishing the new code.
Publishing does not migrate an external production database. Do not add schema
changes to startup or worker commands.
