# Production Schema, Validation, and Brand Data Guide

This guide covers the safe production rollout for the nutrition consistency
checker. It does not copy Development data into Production and does not
truncate or replace production tables.

## 1. Verify Development

Before publishing:

1. Confirm `schema.sql` contains the approved `nutrition_validation` table,
   indexes, and reporting views.
2. Run the focused tests:

   ```bash
   python -m unittest \
     test_nutrition_validator.py \
     test_nutriscore_category_types.py
   ```

3. Confirm the Development Checks tab loads successfully.

## 2. Publish schema changes

Use Replit's **Publish** flow for production schema changes. Replit compares
the Development and Production schemas and applies the required schema diff
during publishing.

Official reference:
https://docs.replit.com/features/data-and-storage/development-and-production

Do not:

- run production DDL from `combined_startup.sh`;
- add startup-time schema mutations;
- copy the Development database over Production;
- truncate or replace production tables.

Publishing creates the additive validation table, indexes, and reporting views.
It does not populate validation results.

## 3. Populate production validation results

After the production schema is available, run:

```bash
python nutrition_validation_backfill.py \
  --production \
  --confirm-production \
  --batch-size 100
```

The command:

- requires both production flags;
- uses `PROD_DATABASE_URL`;
- refuses to run if the configured Development and Production URLs are equal;
- reads existing product, ingredient, and nutrition records;
- writes only to `nutrition_validation`;
- commits in batches and isolates product-level failures with savepoints;
- upserts one current result per product, making reruns idempotent.

If the process is interrupted, use the last committed product ID shown in the
output:

```bash
python nutrition_validation_backfill.py \
  --production \
  --confirm-production \
  --start-id LAST_COMMITTED_PRODUCT_ID \
  --batch-size 100
```

## 4. Verify production

Confirm:

- validation row count equals product count;
- no products are missing validation rows;
- no product has duplicate validation rows;
- level totals add up to the product count;
- the production Checks tab shows summary cards and suspicious findings.

The backfill is a reporting operation only. It never changes scraped source
data or automatically corrects nutrition values.

## 5. Brand and producer rollout

Migration `005_add_brands_and_producers.sql` adds independent `brands` and
`producers` master tables, the many-to-many `brand_producers` table, and
nullable product foreign keys. Apply it through the same Replit Publish schema
flow described above; do not add it to application startup.

After the production schema is available:

```bash
python brand_producer_backfill.py \
  --production \
  --confirm-production \
  --batch-size 25 \
  --delay 0.5
```

The command re-fetches saved Rimi URLs sequentially, uses the existing retry
client, commits in batches, and isolates individual failures. Resume after an
interruption with `--start-id SAFE_RESUME_AFTER_PRODUCT_ID`, using the printed
`resume_after_product_id` value rather than the last attempted ID. If a row
fails, that safe cursor stays before it so the failed row is retried. Reruns are safe:
normalized names and brand-producer pairs are unique, existing canonical names
and website URLs are preserved, and omitted scraped values do not clear a
product's current links.