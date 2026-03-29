"""
Backfill script: fix quantity_value/quantity_unit for products with NxM patterns
in their names (e.g. "25x2g" -> 50g, "6x0,33l" -> 1.98l).

Only updates products whose name contains a NxM pattern - does not touch others.
"""
import sys
import re
from decimal import Decimal

sys.path.append('.')
from database_updater import DatabaseUpdater


def parse_multiplier_pattern(name: str):
    """Return (total_value, unit) for NxM patterns, or (None, None)."""
    pattern = r'(\d+)\s*[xX×]\s*(\d+(?:[.,]\d+)?)\s*(g|kg|ml|l)\b'
    m = re.search(pattern, name.lower())
    if m:
        try:
            multiplier = Decimal(m.group(1))
            unit_qty = Decimal(m.group(2).replace(',', '.'))
            unit = m.group(3).lower()
            return multiplier * unit_qty, unit
        except Exception:
            pass
    return None, None


def main():
    def status(msg):
        print(f"[INFO] {msg}")

    updater = DatabaseUpdater(status)

    try:
        # Fetch all products whose name contains a NxM pattern
        rows = updater._execute_query(
            "SELECT product_id, sku, name, quantity_value, quantity_unit "
            "FROM products WHERE name ~ '[0-9]+[xX][0-9]' ORDER BY name",
            fetch=True
        )
        print(f"Found {len(rows)} products with NxM pattern in name\n")

        updated = 0
        skipped = 0
        errors = 0

        for row in rows:
            pid = row['product_id']
            sku = row['sku']
            name = row['name']
            old_val = row['quantity_value']
            old_unit = row['quantity_unit']

            new_val, new_unit = parse_multiplier_pattern(name)

            if new_val is None:
                print(f"  SKIP (no match): {sku} | {name}")
                skipped += 1
                continue

            if old_val == new_val and old_unit == new_unit:
                skipped += 1
                continue

            try:
                updater._execute_query(
                    "UPDATE products SET quantity_value = %s, quantity_unit = %s WHERE product_id = %s",
                    (new_val, new_unit, pid)
                )
                print(f"  FIXED: {sku} | {name[:60]}")
                print(f"         {old_val} {old_unit}  ->  {new_val} {new_unit}")
                updated += 1
            except Exception as e:
                print(f"  ERROR: {sku} | {e}")
                errors += 1

        # Commit all updates in one transaction
        updater.conn.commit()
        print(f"\n=== RESULTS ===")
        print(f"Updated : {updated}")
        print(f"Skipped : {skipped}")
        print(f"Errors  : {errors}")

        # Spot-check SKU 153419
        check = updater._execute_query(
            "SELECT sku, name, quantity_value, quantity_unit FROM products WHERE sku = '153419'",
            fetch=True
        )
        if check:
            r = check[0]
            print(f"\nSpot-check 153419: quantity_value={r['quantity_value']}, quantity_unit={r['quantity_unit']}")

    finally:
        updater.close()


if __name__ == "__main__":
    main()
