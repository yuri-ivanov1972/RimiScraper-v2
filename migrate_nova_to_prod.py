#!/usr/bin/env python3
"""
migrate_nova_to_prod.py
=======================
One-time migration: add nova_score + nova_source to the production products
table and populate them using the same two-pass logic used on dev.

Pass 1 — additive override
    Products that have at least one ingredient with suspicion_level IN
    ('avoid', 'limit') → nova_score = 4, nova_source = 'additive_override'

Pass 2 — category fallback
    All remaining products → nova_score = category's nova_score (from
    normalized_categories), nova_source = 'category_inherited'

Safe to re-run:
    - Column creation uses IF NOT EXISTS → no error if already present
    - Population skips products that already have a nova_source set
      (so manual_override / additive_override set by a previous run are kept)

Usage:
    python migrate_nova_to_prod.py            # live run
    python migrate_nova_to_prod.py --dry-run  # preview counts, no writes
"""
import os
import sys
import psycopg2


DRY_RUN = '--dry-run' in sys.argv


def connect():
    url = os.environ.get('PROD_DATABASE_URL')
    if not url:
        print("✗ PROD_DATABASE_URL is not set.")
        sys.exit(1)
    return psycopg2.connect(url)


def main():
    mode = "DRY-RUN (no changes will be written)" if DRY_RUN else "LIVE"
    print(f"=== NOVA migration to production — {mode} ===\n")

    conn = connect()
    cur = conn.cursor()

    # ------------------------------------------------------------------
    # Step 1: Add columns (idempotent)
    # ------------------------------------------------------------------
    print("Step 1: Schema — adding nova_score / nova_source columns...")

    cur.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'products' AND table_schema = 'public'
          AND column_name IN ('nova_score', 'nova_source')
    """)
    existing = {r[0] for r in cur.fetchall()}

    for col, defn in [
        ("nova_score",  "INTEGER"),
        ("nova_source", "VARCHAR(30)"),
    ]:
        if col in existing:
            print(f"  ✓ Column '{col}' already exists — skipped")
        else:
            if not DRY_RUN:
                cur.execute(f"ALTER TABLE products ADD COLUMN {col} {defn}")
                print(f"  + Column '{col}' added")
            else:
                print(f"  [dry-run] Would add column '{col} {defn}'")

    if not DRY_RUN:
        conn.commit()

    # ------------------------------------------------------------------
    # Step 2: Count baseline
    # ------------------------------------------------------------------
    cur.execute("SELECT COUNT(*) FROM products")
    total = cur.fetchone()[0]

    if not DRY_RUN:
        cur.execute("SELECT COUNT(*) FROM products WHERE nova_source IS NOT NULL")
        already_set = cur.fetchone()[0]
    else:
        already_set = 0

    print(f"\nStep 2: Population")
    print(f"  Total products : {total}")
    print(f"  Already scored : {already_set} (will be skipped)")
    print(f"  To score       : {total - already_set}")

    # ------------------------------------------------------------------
    # Step 2a: Additive override
    # ------------------------------------------------------------------
    print("\n  Pass 1 — additive override (avoid/limit ingredients → NOVA 4)...")

    # In dry-run the columns don't exist yet, so count without the nova_source filter
    cur.execute("""
        SELECT COUNT(DISTINCT p.product_id)
        FROM products p
        JOIN ingredient_product_mapping ipm ON ipm.product_sku = p.sku
        JOIN ingredient_analysis ia ON ia.id = ipm.ingredient_id
        WHERE ia.suspicion_level IN ('avoid', 'limit')
    """)
    additive_count = cur.fetchone()[0]
    print(f"    Products qualifying: {additive_count}")

    if not DRY_RUN:
        cur.execute("""
            UPDATE products p
            SET nova_score  = 4,
                nova_source = 'additive_override'
            WHERE nova_source IS NULL
              AND EXISTS (
                  SELECT 1
                  FROM ingredient_product_mapping ipm
                  JOIN ingredient_analysis ia ON ia.id = ipm.ingredient_id
                  WHERE ipm.product_sku = p.sku
                    AND ia.suspicion_level IN ('avoid', 'limit')
              )
        """)
        print(f"    ✓ Updated: {cur.rowcount} products → NOVA 4 (additive_override)")
    else:
        print(f"    [dry-run] Would set up to {additive_count} products → NOVA 4 (additive_override)")

    # ------------------------------------------------------------------
    # Step 2b: Category fallback
    # ------------------------------------------------------------------
    print("\n  Pass 2 — category fallback (remaining products inherit from category)...")

    # In dry-run the columns don't exist, so estimate without nova_source filter
    # (actual run will skip additive_override products via nova_source IS NULL)
    cur.execute("""
        SELECT COUNT(*)
        FROM products p
        JOIN normalized_categories nc ON nc.category_id = p.category_id
        WHERE nc.nova_score IS NOT NULL
    """)
    cat_total = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(*)
        FROM products p
        LEFT JOIN normalized_categories nc ON nc.category_id = p.category_id
        WHERE nc.nova_score IS NULL OR nc.category_id IS NULL
    """)
    no_cat_count = cur.fetchone()[0]

    cat_count = cat_total - additive_count  # rough estimate for dry-run
    print(f"    Products with a category NOVA : {cat_total} total "
          f"(~{cat_count} after pass 1, skipping additive ones)")
    print(f"    Products with no category NOVA: {no_cat_count} (will stay NULL)")

    if not DRY_RUN:
        cur.execute("""
            UPDATE products p
            SET nova_score  = nc.nova_score,
                nova_source = 'category_inherited'
            FROM normalized_categories nc
            WHERE p.category_id = nc.category_id
              AND p.nova_source IS NULL
              AND nc.nova_score IS NOT NULL
        """)
        print(f"    ✓ Updated: {cur.rowcount} products → category_inherited")
        conn.commit()
    else:
        print(f"    [dry-run] Would set ~{max(cat_count, 0)} products → category_inherited")

    # ------------------------------------------------------------------
    # Step 3: Summary
    # ------------------------------------------------------------------
    print(f"\n{'='*55}")
    print("Summary after migration:")

    if not DRY_RUN:
        cur.execute("""
            SELECT nova_source, nova_score, COUNT(*)
            FROM products
            GROUP BY nova_source, nova_score
            ORDER BY nova_source NULLS LAST, nova_score
        """)
        rows = cur.fetchall()
        for source, score, cnt in rows:
            src_label = source or "(no source — NULL)"
            score_label = f"NOVA {score}" if score else "NULL"
            print(f"  {src_label:25s}  {score_label:8s}  {cnt} products")

        cur.execute("SELECT COUNT(*) FROM products WHERE nova_score IS NULL")
        null_count = cur.fetchone()[0]
        if null_count:
            print(f"\n  ⚠ {null_count} products still have no NOVA score (no category mapping)")
        else:
            print(f"\n  ✓ All products have a NOVA score")
    else:
        print(f"  Dry-run — no data written. Remove --dry-run to apply.")

    print(f"{'='*55}")

    cur.close()
    conn.close()
    print("\nDone.")


if __name__ == '__main__':
    main()
