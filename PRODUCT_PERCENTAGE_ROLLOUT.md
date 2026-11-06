# Fruit, vegetable and legume percentage

In **Products → product details → edit nutrition**, enter a percentage between
0 and 100 (up to two decimal places) to save a manual override, including an
explicit 0%. Leave the field empty, or delete its contents and save, to use the
category default shown below the field. There is no separate default checkbox.
The normal save button recalculates Nutri-Score.

The override is independent of the general manual-nutrition checkbox. Scraping,
USDA enrichment and table-backed recalculations read it without overwriting it.
It counts fruit, vegetables and legumes, not nuts.

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
