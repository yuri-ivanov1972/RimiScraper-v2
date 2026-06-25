"""
nova_calculator.py
==================
Single-product NOVA score assignment using the two-pass rule:

  Pass 1 (additive_override):
      If any ingredient linked to the product has suspicion_level IN
      ('avoid', 'limit') → nova_score = 4, nova_source = 'additive_override'

  Pass 2 (category_inherited):
      Otherwise → nova_score = category's nova_score (from
      normalized_categories), nova_source = 'category_inherited'

Rules:
  - Products with nova_source = 'manual_override' are never touched.
  - If the category has no nova_score set, nova_score stays NULL and
    nova_source is set to 'category_inherited' (so it will be picked up
    automatically once the category gets a score).
"""
import logging

logger = logging.getLogger(__name__)


def assign_nova_score(conn, product_id: int, sku: str) -> dict:
    """
    Calculate and write nova_score + nova_source for a single product.

    Parameters
    ----------
    conn : psycopg2 connection (already open, caller manages commit/close)
    product_id : int
    sku : str

    Returns
    -------
    dict with keys: nova_score, nova_source, skipped (bool), reason (str)
    """
    try:
        with conn.cursor() as cur:
            # --- Guard: never overwrite a manual override ---
            cur.execute(
                "SELECT nova_source FROM products WHERE product_id = %s",
                (product_id,)
            )
            row = cur.fetchone()
            if row and row[0] == 'manual_override':
                return {
                    'nova_score': None,
                    'nova_source': 'manual_override',
                    'skipped': True,
                    'reason': 'manual_override — not touched',
                }

            # --- Pass 1: additive override ---
            cur.execute(
                """
                SELECT COUNT(*) FROM ingredient_product_mapping ipm
                JOIN ingredient_analysis ia ON ia.id = ipm.ingredient_id
                WHERE ipm.product_sku = %s
                  AND ia.suspicion_level IN ('avoid', 'limit')
                """,
                (sku,)
            )
            bad_count = cur.fetchone()[0]

            if bad_count > 0:
                nova_score = 4
                nova_source = 'additive_override'
            else:
                # --- Pass 2: category fallback ---
                cur.execute(
                    """
                    SELECT nc.nova_score
                    FROM products p
                    JOIN normalized_categories nc ON nc.category_id = p.category_id
                    WHERE p.product_id = %s
                    """,
                    (product_id,)
                )
                cat_row = cur.fetchone()
                nova_score = cat_row[0] if cat_row else None
                nova_source = 'category_inherited'

            cur.execute(
                """
                UPDATE products
                SET nova_score = %s, nova_source = %s
                WHERE product_id = %s
                """,
                (nova_score, nova_source, product_id)
            )
            conn.commit()

            logger.debug(
                "NOVA assigned: product_id=%s sku=%s → %s (%s)",
                product_id, sku, nova_score, nova_source
            )
            return {
                'nova_score': nova_score,
                'nova_source': nova_source,
                'skipped': False,
                'reason': 'ok',
            }

    except Exception as exc:
        logger.warning(
            "NOVA assignment failed for product_id=%s sku=%s: %s",
            product_id, sku, exc
        )
        return {
            'nova_score': None,
            'nova_source': None,
            'skipped': True,
            'reason': str(exc),
        }
