# Database Migration Guide: Development → Production

This guide explains how to migrate all data from your development database to your production database on the Reserved VM deployment.

## Overview

The `migrate_to_production.py` script copies all 12 tables from development to production in the correct order to respect foreign key constraints.

### Tables Migrated (in dependency order)

**CRITICAL**: Parent tables are migrated BEFORE child tables to prevent CASCADE deletions.

1. **Base tables** (no dependencies):
   - `normalized_categories` - Your 75 level2 categories
   - `ingredient_analysis` - E-number and ingredient data

2. **Products table** (depends on categories):
   - `products` - All product information

3. **Job table** (parent of workers and other job-related tables):
   - `category_processing_jobs` - Job queue with processing history

4. **Worker table** (depends on jobs):
   - `processing_workers` - Worker registration data (has FK to category_processing_jobs)

5. **Product-related tables** (depend on products):
   - `nutritionfacts` - Nutritional information
   - `productphotos` - Product photos from Rimi CDN
   - `product_price_history` - Historical pricing data

6. **Job-related tables** (depend on jobs):
   - `job_events` - Job lifecycle event logs
   - `product_processing_log` - Per-product processing logs
   - `update_statistics` - Category update statistics

7. **Mapping tables**:
   - `ingredient_product_mapping` - Links ingredients to products

## Prerequisites

### 1. Get Your Production Database Connection String

You need the production database connection URL from Replit:

1. Open your **Reserved VM deployment** in Replit
2. Go to the **Database** pane
3. Click on **"Production"** tab
4. Copy the connection string (format: `postgresql://user:password@host:port/database`)

### 2. Set Environment Variable

Set the production database URL as an environment variable:

```bash
export PROD_DATABASE_URL='postgresql://user:password@host:port/database'
```

**Important**: Replace the connection string with your actual production database URL.

## Running the Migration

### Replit publish-time schema migration

The Reserved VM publish command runs `combined_startup.sh`. Before Streamlit or
the worker starts, it runs:

```bash
python apply_nutrition_validation_schema.py --production
```

This applies `migrations/004_add_nutrition_validation.sql` to
`PROD_DATABASE_URL` and verifies the `nutrition_validation` table, its two
reporting indexes, and all three reporting views. The migration is additive and
idempotent. It does not copy development findings or run the validation
backfill. A migration or verification failure stops deployment startup.

### Step 1: Verify Development Database

First, check that your development database has data to migrate:

```bash
python -c "
import os
import psycopg2
conn = psycopg2.connect(os.environ['DATABASE_URL'])
cursor = conn.cursor()
cursor.execute('SELECT COUNT(*) FROM normalized_categories')
print(f'Categories: {cursor.fetchone()[0]}')
cursor.execute('SELECT COUNT(*) FROM products')
print(f'Products: {cursor.fetchone()[0]}')
cursor.close()
conn.close()
"
```

### Step 2: Run Migration Script

Execute the migration:

```bash
python migrate_to_production.py
```

### Step 3: Review Output

The script will:
- ✅ Connect to both databases
- ✅ Show progress for each table
- ✅ Display record counts (source → destination)
- ✅ Verify all data was copied correctly
- ✅ Reset auto-increment sequences

**Example output:**

```
==============================================================
            DATABASE MIGRATION: DEV → PROD
==============================================================

ℹ Connecting to development database...
✓ Connected to development database
ℹ Connecting to production database...
✓ Connected to production database

==============================================================
                    STARTING MIGRATION
==============================================================

ℹ Migrating table: normalized_categories
ℹ   Source records: 75
ℹ   Truncating destination table...
ℹ   Inserted 75/75 records...
✓   ✓ Migration complete: 75 records

ℹ Migrating table: products
ℹ   Source records: 8205
ℹ   Truncating destination table...
ℹ   Inserted 1000/8205 records...
ℹ   Inserted 2000/8205 records...
...
✓   ✓ Migration complete: 8205 records

...

==============================================================
                    MIGRATION SUMMARY
==============================================================

✓ normalized_categories                  75 →       75
✓ ingredient_analysis                   450 →      450
✓ products                             8205 →     8205
✓ processing_workers                      3 →        3
✓ category_processing_jobs              190 →      190
✓ nutritionfacts                       7821 →     7821
✓ productphotos                       16410 →    16410
✓ product_price_history                8205 →     8205
✓ job_events                            856 →      856
✓ product_processing_log               8205 →     8205
✓ update_statistics                     190 →      190
✓ ingredient_product_mapping          12450 →    12450

ℹ Total records migrated: 63060
ℹ Total tables migrated: 12
ℹ Migration completed in 45.32 seconds
✓ All tables migrated successfully!
```

## Important Notes

### Data Safety

- ⚠️ **The script TRUNCATES (deletes all data) in production tables before copying**
- This ensures a clean migration without duplicates
- If you need to preserve existing production data, modify the script to use `UPSERT` logic instead

### Foreign Key Handling

- The script temporarily disables foreign key constraints during migration
- This allows faster bulk inserts without constraint checking overhead
- Constraints are re-enabled after migration completes

### Sequence Reset

- Auto-increment sequences are automatically reset to match the maximum ID values
- This ensures new records get correct IDs after migration

### Error Handling

If migration fails:

1. **Check error message** - The script shows detailed error information
2. **Verify connection strings** - Ensure both DATABASE_URL and PROD_DATABASE_URL are correct
3. **Check permissions** - Production database user must have CREATE, INSERT, DELETE permissions
4. **Review logs** - Look for network issues or timeout errors

The script is **safe to re-run** - it will truncate and re-migrate all data.

## Post-Migration Verification

After migration completes, verify your production database:

```bash
# Connect to production database
export DATABASE_URL="$PROD_DATABASE_URL"

# Check record counts
python -c "
import os
import psycopg2
conn = psycopg2.connect(os.environ['PROD_DATABASE_URL'])
cursor = conn.cursor()

tables = [
    'normalized_categories',
    'products',
    'category_processing_jobs',
    'nutritionfacts'
]

for table in tables:
    cursor.execute(f'SELECT COUNT(*) FROM {table}')
    count = cursor.fetchone()[0]
    print(f'{table}: {count} records')

cursor.close()
conn.close()
"
```

## Starting Worker on Production

After successful migration, you can start the worker on your Reserved VM:

```bash
python worker.py --resume-all --heartbeat-interval 30 --chunk-size 15 --max-workers 3
```

The worker will:
- ✅ Find all your migrated jobs in `category_processing_jobs`
- ✅ Resume processing from where it left off
- ✅ Use optimal settings for Reserved VM (no timeout limits)

## Troubleshooting

### Problem: "PROD_DATABASE_URL not set"

**Solution**: Export the environment variable before running:

```bash
export PROD_DATABASE_URL='your_production_connection_string'
python migrate_to_production.py
```

### Problem: "Permission denied on table"

**Solution**: Ensure your production database user has proper permissions:

```sql
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO your_user;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO your_user;
```

### Problem: "Connection timeout"

**Solution**: Check that:
- Your production database is accessible
- Firewall rules allow connections
- Connection string is correct (host, port, credentials)

### Problem: Record count mismatch

**Solution**: 
- Re-run the migration (script is idempotent)
- Check for schema differences between dev and prod
- Verify all tables exist in production database

## Next Steps

After successful migration:

1. ✅ Verify production database has all data
2. ✅ Test Streamlit UI on production deployment
3. ✅ Start worker with Reserved VM settings
4. ✅ Monitor job processing and logs
5. ✅ Set up daily auto-updates at 2am Latvia time

---

**Questions or issues?** Check the migration output for detailed error messages or review the script source code in `migrate_to_production.py`.
