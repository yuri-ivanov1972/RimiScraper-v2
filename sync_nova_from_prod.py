#!/usr/bin/env python3
"""
Sync NOVA classification from production → development database.

Reads nova_score + nova_score_explicit from prod's normalized_categories
and applies them to dev, matching on rimi_category_code.

Safe: only touches the two NOVA columns; read-only on production.
Idempotent: can be run multiple times.
"""
import os
import sys
import psycopg2

def main():
    dev_url = os.environ.get('DATABASE_URL')
    prod_url = os.environ.get('PROD_DATABASE_URL')

    if not dev_url:
        print("✗ DATABASE_URL not set")
        sys.exit(1)
    if not prod_url:
        print("✗ PROD_DATABASE_URL not set")
        sys.exit(1)

    print("Connecting to production database (read)...")
    prod_conn = psycopg2.connect(prod_url)
    print("Connecting to development database (write)...")
    dev_conn = psycopg2.connect(dev_url)

    prod_cur = prod_conn.cursor()
    dev_cur = dev_conn.cursor()

    # Read all NOVA-assigned categories from prod
    prod_cur.execute("""
        SELECT rimi_category_code, nova_score, nova_score_explicit
        FROM normalized_categories
        WHERE nova_score IS NOT NULL
        ORDER BY rimi_category_code
    """)
    prod_rows = prod_cur.fetchall()
    print(f"\nFound {len(prod_rows)} categories with NOVA data in production")

    updated = 0
    not_found = 0
    skipped_null = 0
    errors = []

    for rimi_code, nova_score, nova_explicit in prod_rows:
        try:
            dev_cur.execute("""
                UPDATE normalized_categories
                SET nova_score = %s,
                    nova_score_explicit = %s
                WHERE rimi_category_code = %s
            """, (nova_score, nova_explicit, rimi_code))

            if dev_cur.rowcount == 1:
                updated += 1
            else:
                not_found += 1
                print(f"  ⚠ Not found in dev: {rimi_code}")
        except Exception as e:
            errors.append((rimi_code, str(e)))

    dev_conn.commit()

    # Summary
    print(f"\n{'='*50}")
    print(f"✓ Updated:    {updated} categories")
    print(f"⚠ Not found:  {not_found} categories (in prod but not in dev)")
    if errors:
        print(f"✗ Errors:     {len(errors)}")
        for code, err in errors:
            print(f"    {code}: {err}")
    print(f"{'='*50}")

    # Verify result in dev
    dev_cur.execute("""
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE nova_score IS NOT NULL) AS has_nova,
            COUNT(*) FILTER (WHERE nova_score_explicit = TRUE) AS explicit
        FROM normalized_categories
    """)
    row = dev_cur.fetchone()
    print(f"\nDev after sync: {row[1]}/{row[0]} categories have NOVA ({row[2]} explicitly set)")

    # --- Sync products that inherited their NOVA from the category ---
    print("\nSyncing product nova_score for nova_source='category_inherited'...")
    dev_cur.execute("""
        UPDATE products p
        SET nova_score = nc.nova_score
        FROM normalized_categories nc
        WHERE p.category_id = nc.category_id
          AND p.nova_source = 'category_inherited'
    """)
    products_updated = dev_cur.rowcount
    dev_conn.commit()
    print(f"✓ Products updated: {products_updated}")

    dev_cur.execute("""
        SELECT nova_score, COUNT(*) FROM products
        WHERE nova_source = 'category_inherited'
        GROUP BY nova_score ORDER BY nova_score
    """)
    print("  Breakdown (category_inherited):")
    for score, cnt in dev_cur.fetchall():
        print(f"    NOVA {score}: {cnt} products")

    prod_conn.close()
    dev_conn.close()
    print("\nDone.")

if __name__ == '__main__':
    main()
