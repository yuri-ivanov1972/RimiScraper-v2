# Initialize the Estonia Project Database

This project starts with an empty PostgreSQL database. The initialization
command creates the application structure only: tables, relationships,
indexes, the `pg_trgm` extension, and the `product_ingredient_cards`
materialized view. It does **not** copy products, categories, prices, or any
other data from the Latvian project.

## Before you start

1. Create or connect a PostgreSQL database for this Estonia project.
2. Add its connection string as the project secret named `DATABASE_URL`.
3. Make sure the database user can create tables, indexes, materialized views,
   and the `pg_trgm` extension.
4. Use UTF-8 database encoding. This is required for Latvian and Estonian
   product/category text.

Do not paste the connection string into source code or commit it to the
repository.

## Run the initializer

From the project root, run:

```bash
python init_database.py
```

Expected output:

```text
Database schema initialized successfully.
Verified 13 application tables and product_ingredient_cards.
No product, category, price, or other source data was imported.
```

The command is safe to run again after a successful initialization. It refuses
to modify a partially created Rimi scraper schema so it cannot silently leave
the database in an inconsistent state.

## Verify the empty database

Run this in the Shell after initialization:

```bash
psql "$DATABASE_URL" -c "\dt"
psql "$DATABASE_URL" -c "\d products"
psql "$DATABASE_URL" -c "SELECT COUNT(*) AS products FROM products;"
```

The last command should return `0` before the scraper starts collecting
Estonian categories and products.

## Next step

Start the Streamlit app or the scraper only after the database has been
initialized successfully. The scraper will populate Estonian categories and
products as it runs.