"""
Database queries for Product View UI
Handles hierarchical category tree and product listing with pagination
"""

import psycopg2
from psycopg2.extras import RealDictCursor
import os
from typing import List, Dict, Optional, Tuple


class ProductViewDatabase:
    """Database manager for Product View UI"""
    
    def __init__(self):
        self.connection = None
        self._connect()
    
    def _connect(self):
        """Establish database connection"""
        try:
            self.connection = psycopg2.connect(
                os.environ['DATABASE_URL'],
                cursor_factory=RealDictCursor
            )
        except Exception as e:
            raise Exception(f"Database connection failed: {str(e)}")
    
    def _ensure_connection(self):
        """Ensure database connection is active"""
        if self.connection is None or self.connection.closed:
            self._connect()
    
    def get_hierarchical_categories(self) -> List[Dict]:
        """
        Get all categories in hierarchical structure
        Returns list of categories with parent-child relationships
        """
        self._ensure_connection()
        
        query = """
        SELECT 
            category_id,
            rimi_category_code,
            name_lv,
            name_en,
            level,
            parent_category_id
        FROM normalized_categories
        ORDER BY rimi_category_code
        """
        
        with self.connection.cursor() as cursor:
            cursor.execute(query)
            return cursor.fetchall()
    
    def build_category_tree(self) -> List[Dict]:
        """
        Build hierarchical category tree structure
        Returns nested dictionary structure suitable for UI rendering
        """
        categories = self.get_hierarchical_categories()
        
        # Create lookup dictionary
        category_map = {cat['category_id']: dict(cat) for cat in categories}
        
        # Add children lists
        for cat in category_map.values():
            cat['children'] = []
            cat['product_count'] = 0
        
        # Build tree structure
        root_categories = []
        for cat in category_map.values():
            if cat['parent_category_id'] is None:
                root_categories.append(cat)
            else:
                parent = category_map.get(cat['parent_category_id'])
                if parent:
                    parent['children'].append(cat)
        
        return root_categories
    
    def get_category_product_counts(self) -> Dict[int, int]:
        """Get product count for each category"""
        self._ensure_connection()
        
        query = """
        SELECT 
            category_id,
            COUNT(*) as product_count
        FROM products
        GROUP BY category_id
        """
        
        with self.connection.cursor() as cursor:
            cursor.execute(query)
            results = cursor.fetchall()
            return {row['category_id']: row['product_count'] for row in results}
    
    def get_products_by_category(
        self, 
        category_id: Optional[int] = None,
        page: int = 1,
        page_size: int = 20,
        include_subcategories: bool = True
    ) -> Tuple[List[Dict], int]:
        """
        Get products for a category with pagination
        
        Args:
            category_id: Category to filter by (None = all products)
            page: Page number (1-indexed)
            page_size: Number of products per page
            include_subcategories: Include products from subcategories
        
        Returns:
            Tuple of (products list, total count)
        """
        self._ensure_connection()
        
        offset = (page - 1) * page_size
        
        # Build category filter
        if category_id is not None:
            if include_subcategories:
                # Get all subcategory IDs
                category_ids = self._get_category_and_subcategories(category_id)
                category_filter = f"p.category_id = ANY(ARRAY{category_ids})"
            else:
                category_filter = f"p.category_id = {category_id}"
        else:
            category_filter = "1=1"  # No filter
        
        # Query for products
        query = f"""
        SELECT 
            p.product_id,
            p.sku,
            p.name,
            p.category_id,
            p.quantity_value,
            p.quantity_unit,
            p.rimi_url,
            nc.rimi_category_code,
            nc.name_lv as category_name,
            nf.nutri_score_grade,
            nf.carbs_sugars,
            nf.fat_total,
            nf.protein,
            nf.salt,
            nf.energy_kj,
            pp.photo_url,
            p.nova_score,
            p.nova_source
        FROM products p
        LEFT JOIN normalized_categories nc ON p.category_id = nc.category_id
        LEFT JOIN nutritionfacts nf ON p.product_id = nf.product_id
        LEFT JOIN LATERAL (
            SELECT photo_url 
            FROM productphotos 
            WHERE product_id = p.product_id 
            ORDER BY is_primary DESC, photo_id 
            LIMIT 1
        ) pp ON true
        WHERE {category_filter}
        ORDER BY p.name
        LIMIT %s OFFSET %s
        """
        
        # Count query
        count_query = f"""
        SELECT COUNT(*) as total
        FROM products p
        WHERE {category_filter}
        """
        
        with self.connection.cursor() as cursor:
            # Get total count
            cursor.execute(count_query)
            total = cursor.fetchone()['total']
            
            # Get products
            cursor.execute(query, (page_size, offset))
            products = cursor.fetchall()
            
            return products, total
    
    def _get_category_and_subcategories(self, category_id: int) -> List[int]:
        """
        Recursively get category ID and all subcategory IDs
        """
        self._ensure_connection()
        
        query = """
        WITH RECURSIVE category_tree AS (
            SELECT category_id, parent_category_id
            FROM normalized_categories
            WHERE category_id = %s
            
            UNION ALL
            
            SELECT nc.category_id, nc.parent_category_id
            FROM normalized_categories nc
            INNER JOIN category_tree ct ON nc.parent_category_id = ct.category_id
        )
        SELECT category_id FROM category_tree
        """
        
        with self.connection.cursor() as cursor:
            cursor.execute(query, (category_id,))
            return [row['category_id'] for row in cursor.fetchall()]
    
    def get_product_details(self, product_id: int) -> Optional[Dict]:
        """
        Get complete product details including nutrition, ingredients, photos
        """
        self._ensure_connection()
        
        # Main product query
        product_query = """
        SELECT 
            p.product_id,
            p.sku,
            p.name,
            p.category_id,
            p.quantity_value,
            p.quantity_unit,
            p.rimi_url,
            p.country_of_origin,
            nc.rimi_category_code,
            nc.name_lv as category_name,
            nf.nutri_score_grade,
            nf.nutri_score_points,
            nf.energy_kcal,
            nf.energy_kj,
            nf.fat_total,
            nf.fat_saturated,
            nf.carbs_total,
            nf.carbs_sugars,
            nf.protein,
            nf.salt,
            nf.fiber,
            nf.ingredients_text,
            COALESCE(nf.nutrition_manual_edit, FALSE) as nutrition_manual_edit,
            p.nova_score,
            p.nova_source,
            p.is_hidden
        FROM products p
        LEFT JOIN normalized_categories nc ON p.category_id = nc.category_id
        LEFT JOIN nutritionfacts nf ON p.product_id = nf.product_id
        WHERE p.product_id = %s
        """
        
        # Photos query
        photos_query = """
        SELECT photo_url, is_primary
        FROM productphotos
        WHERE product_id = %s
        ORDER BY is_primary DESC, photo_id
        """
        
        # Price history query (latest price)
        price_query = """
        SELECT price, created_at
        FROM product_price_history
        WHERE product_id = %s
        ORDER BY created_at DESC
        LIMIT 1
        """
        
        with self.connection.cursor() as cursor:
            # Get product
            cursor.execute(product_query, (product_id,))
            product = cursor.fetchone()
            
            if not product:
                return None
            
            product = dict(product)
            
            # Get photos
            cursor.execute(photos_query, (product_id,))
            product['photos'] = [row['photo_url'] for row in cursor.fetchall()]
            
            # Get latest price
            cursor.execute(price_query, (product_id,))
            price_row = cursor.fetchone()
            if price_row:
                product['price'] = float(price_row['price'])
                product['price_date'] = price_row['created_at']
            else:
                product['price'] = None
                product['price_date'] = None
            
            return product
    
    def search_products(self, search_term: str, page: int = 1, page_size: int = 20) -> Tuple[List[Dict], int]:
        """
        Search products by name
        
        Args:
            search_term: Search string
            page: Page number
            page_size: Results per page
        
        Returns:
            Tuple of (products list, total count)
        """
        self._ensure_connection()
        
        offset = (page - 1) * page_size
        search_pattern = f"%{search_term.lower()}%"
        
        query = """
        SELECT 
            p.product_id,
            p.sku,
            p.name,
            p.category_id,
            p.quantity_value,
            p.quantity_unit,
            nc.rimi_category_code,
            nc.name_lv as category_name,
            nf.nutri_score_grade,
            nf.carbs_sugars,
            nf.fat_total,
            nf.protein,
            nf.salt,
            pp.photo_url,
            p.nova_score,
            p.nova_source
        FROM products p
        LEFT JOIN normalized_categories nc ON p.category_id = nc.category_id
        LEFT JOIN nutritionfacts nf ON p.product_id = nf.product_id
        LEFT JOIN LATERAL (
            SELECT photo_url 
            FROM productphotos 
            WHERE product_id = p.product_id 
            ORDER BY is_primary DESC, photo_id 
            LIMIT 1
        ) pp ON true
        WHERE LOWER(p.name) LIKE %s
        ORDER BY p.name
        LIMIT %s OFFSET %s
        """
        
        count_query = """
        SELECT COUNT(*) as total
        FROM products
        WHERE LOWER(name) LIKE %s
        """
        
        with self.connection.cursor() as cursor:
            cursor.execute(count_query, (search_pattern,))
            total = cursor.fetchone()['total']
            
            cursor.execute(query, (search_pattern, page_size, offset))
            products = cursor.fetchall()
            
            return products, total
    
    # ------------------------------------------------------------------
    # NOVA classification helpers
    # ------------------------------------------------------------------

    def get_categories_with_nova(self) -> List[Dict]:
        """Return all categories with nova_score, nova_score_explicit, and direct product count."""
        self._ensure_connection()
        query = """
        SELECT
            nc.category_id,
            nc.rimi_category_code,
            nc.name_lv,
            nc.name_en,
            nc.level,
            nc.parent_category_id,
            nc.nova_score,
            nc.nova_score_explicit,
            COUNT(p.product_id) AS product_count
        FROM normalized_categories nc
        LEFT JOIN products p ON p.category_id = nc.category_id
        GROUP BY nc.category_id, nc.rimi_category_code, nc.name_lv, nc.name_en,
                 nc.level, nc.parent_category_id, nc.nova_score, nc.nova_score_explicit
        ORDER BY nc.rimi_category_code
        """
        with self.connection.cursor() as cursor:
            cursor.execute(query)
            return [dict(row) for row in cursor.fetchall()]

    def get_nova_stats(self) -> Dict:
        """Return summary counts for categories and products (tagged vs untagged)."""
        self._ensure_connection()
        query = """
        SELECT
            COUNT(DISTINCT nc.category_id)                                                          AS total,
            COUNT(DISTINCT nc.category_id) FILTER (WHERE nc.nova_score IS NOT NULL)                AS tagged,
            COUNT(DISTINCT nc.category_id) FILTER (WHERE nc.nova_score IS NULL)                    AS untagged,
            COUNT(DISTINCT nc.category_id) FILTER (WHERE nc.nova_score_explicit = TRUE)            AS explicit,
            COUNT(p.product_id)                                                                     AS total_products,
            COUNT(p.product_id) FILTER (WHERE nc.nova_score IS NOT NULL)                           AS tagged_products,
            COUNT(p.product_id) FILTER (WHERE nc.nova_score IS NULL)                               AS untagged_products
        FROM normalized_categories nc
        LEFT JOIN products p ON p.category_id = nc.category_id
        """
        with self.connection.cursor() as cursor:
            cursor.execute(query)
            return dict(cursor.fetchone())

    def _sync_products_nova_in_category(self, cursor, category_id: int, nova_score) -> int:
        """
        Update nova_score on products that sit in category_id and inherited
        their score from the category (nova_source = 'category_inherited').
        nova_score=None sets the column to NULL.
        Returns number of products updated.
        """
        cursor.execute(
            """
            UPDATE products
            SET nova_score = %s
            WHERE category_id = %s
              AND nova_source = 'category_inherited'
            """,
            (nova_score, category_id)
        )
        return cursor.rowcount

    def set_category_nova(self, category_id: int, nova_score: int) -> None:
        """Set nova_score on a single category and mark it as explicitly set."""
        self._ensure_connection()
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE normalized_categories
                SET nova_score = %s, nova_score_explicit = TRUE
                WHERE category_id = %s
                """,
                (nova_score, category_id)
            )
            self._sync_products_nova_in_category(cursor, category_id, nova_score)
        self.connection.commit()

    def cascade_nova_to_children(self, category_id: int, nova_score: int) -> int:
        """
        Recursively propagate nova_score to all descendants where
        nova_score_explicit is NOT TRUE (i.e. not manually overridden).
        Returns the number of category rows updated.
        Also updates products with nova_source='category_inherited' in all
        affected categories.
        """
        self._ensure_connection()
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                WITH RECURSIVE descendants AS (
                    SELECT category_id
                    FROM normalized_categories
                    WHERE parent_category_id = %s
                    UNION ALL
                    SELECT nc.category_id
                    FROM normalized_categories nc
                    JOIN descendants d ON nc.parent_category_id = d.category_id
                )
                UPDATE normalized_categories
                SET nova_score = %s
                WHERE category_id IN (SELECT category_id FROM descendants)
                  AND (nova_score_explicit IS NOT TRUE)
                """,
                (category_id, nova_score)
            )
            updated = cursor.rowcount
            # Mirror the same change on products in all affected categories
            cursor.execute(
                """
                WITH RECURSIVE descendants AS (
                    SELECT category_id
                    FROM normalized_categories
                    WHERE parent_category_id = %s
                    UNION ALL
                    SELECT nc.category_id
                    FROM normalized_categories nc
                    JOIN descendants d ON nc.parent_category_id = d.category_id
                )
                UPDATE products
                SET nova_score = %s
                WHERE category_id IN (
                    SELECT d.category_id FROM descendants d
                    JOIN normalized_categories nc ON nc.category_id = d.category_id
                    WHERE nc.nova_score_explicit IS NOT TRUE
                )
                  AND nova_source = 'category_inherited'
                """,
                (category_id, nova_score)
            )
        self.connection.commit()
        return updated

    def unset_category_nova(self, category_id: int) -> None:
        """Completely remove nova_score from a category (sets to NULL, clears explicit flag)."""
        self._ensure_connection()
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE normalized_categories
                SET nova_score = NULL, nova_score_explicit = FALSE
                WHERE category_id = %s
                """,
                (category_id,)
            )
            self._sync_products_nova_in_category(cursor, category_id, None)
        self.connection.commit()

    def clear_category_nova_override(self, category_id: int) -> None:
        """
        Clear the explicit override for a category.
        Resets nova_score_explicit = FALSE and re-applies the parent's
        nova_score (if available).
        Also syncs products with nova_source='category_inherited' in this category.
        """
        self._ensure_connection()
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE normalized_categories child
                SET nova_score_explicit = FALSE,
                    nova_score = parent.nova_score
                FROM normalized_categories parent
                WHERE child.category_id = %s
                  AND parent.category_id = child.parent_category_id
                """,
                (category_id,)
            )
            if cursor.rowcount == 0:
                # No parent found (root category) — just clear explicit flag and score
                cursor.execute(
                    """
                    UPDATE normalized_categories
                    SET nova_score_explicit = FALSE, nova_score = NULL
                    WHERE category_id = %s
                    """,
                    (category_id,)
                )
            # Sync products: read the new category score and apply it
            cursor.execute(
                "SELECT nova_score FROM normalized_categories WHERE category_id = %s",
                (category_id,)
            )
            row = cursor.fetchone()
            new_score = row[0] if row else None
            self._sync_products_nova_in_category(cursor, category_id, new_score)
        self.connection.commit()

    # ------------------------------------------------------------------
    # Nutri-Score category type helpers
    # ------------------------------------------------------------------

    def get_categories_with_ns_type(self) -> List[Dict]:
        """Return all categories with nutriscore_category_type info and direct product count."""
        self._ensure_connection()
        query = """
        SELECT
            nc.category_id,
            nc.rimi_category_code,
            nc.name_lv,
            nc.name_en,
            nc.level,
            nc.parent_category_id,
            nc.nutriscore_category_type,
            nc.nutriscore_category_type_explicit,
            COUNT(p.product_id) AS product_count
        FROM normalized_categories nc
        LEFT JOIN products p ON p.category_id = nc.category_id
        GROUP BY nc.category_id, nc.rimi_category_code, nc.name_lv, nc.name_en,
                 nc.level, nc.parent_category_id,
                 nc.nutriscore_category_type, nc.nutriscore_category_type_explicit
        ORDER BY nc.rimi_category_code
        """
        with self.connection.cursor() as cursor:
            cursor.execute(query)
            return [dict(row) for row in cursor.fetchall()]

    def get_ns_type_stats(self) -> Dict:
        """Return summary counts: typed vs untyped categories, breakdown per type."""
        self._ensure_connection()
        query = """
        SELECT
            COUNT(*)                                                                           AS total,
            COUNT(*) FILTER (WHERE nutriscore_category_type IS NOT NULL)                      AS typed,
            COUNT(*) FILTER (WHERE nutriscore_category_type IS NULL)                          AS untyped,
            COUNT(*) FILTER (WHERE nutriscore_category_type = 'beverage')                     AS beverage,
            COUNT(*) FILTER (WHERE nutriscore_category_type = 'cheese')                       AS cheese,
            COUNT(*) FILTER (WHERE nutriscore_category_type = 'red_meat')                     AS red_meat,
            COUNT(*) FILTER (WHERE nutriscore_category_type = 'fat_oil_nut')                  AS fat_oil_nut,
            COUNT(*) FILTER (WHERE nutriscore_category_type = 'full_fvn')                     AS full_fvn,
            COUNT(*) FILTER (WHERE nutriscore_category_type = 'half_fvn')                     AS half_fvn
        FROM normalized_categories
        """
        with self.connection.cursor() as cursor:
            cursor.execute(query)
            return dict(cursor.fetchone())

    def set_category_ns_type(self, category_id: int, ns_type: str) -> None:
        """Set nutriscore_category_type on a single category and mark it as explicitly set."""
        self._ensure_connection()
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE normalized_categories
                SET nutriscore_category_type = %s, nutriscore_category_type_explicit = TRUE
                WHERE category_id = %s
                """,
                (ns_type, category_id)
            )
        self.connection.commit()

    def cascade_ns_type_to_children(self, category_id: int, ns_type: str) -> int:
        """
        Recursively propagate ns_type to all descendants where
        nutriscore_category_type_explicit is NOT TRUE (not manually overridden).
        Returns the number of category rows updated.
        """
        self._ensure_connection()
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                WITH RECURSIVE descendants AS (
                    SELECT category_id
                    FROM normalized_categories
                    WHERE parent_category_id = %s
                    UNION ALL
                    SELECT nc.category_id
                    FROM normalized_categories nc
                    JOIN descendants d ON nc.parent_category_id = d.category_id
                )
                UPDATE normalized_categories
                SET nutriscore_category_type = %s
                WHERE category_id IN (SELECT category_id FROM descendants)
                  AND (nutriscore_category_type_explicit IS NOT TRUE)
                """,
                (category_id, ns_type)
            )
            updated = cursor.rowcount
        self.connection.commit()
        return updated

    def clear_category_ns_type_override(self, category_id: int) -> None:
        """
        Clear the explicit override for a category and re-inherit type from parent.
        Cascades the new (inherited or NULL) type to non-explicit descendants.
        """
        self._ensure_connection()
        with self.connection.cursor() as cursor:
            # Re-inherit from parent
            cursor.execute(
                """
                UPDATE normalized_categories child
                SET nutriscore_category_type_explicit = FALSE,
                    nutriscore_category_type = parent.nutriscore_category_type
                FROM normalized_categories parent
                WHERE child.category_id = %s
                  AND parent.category_id = child.parent_category_id
                """,
                (category_id,)
            )
            if cursor.rowcount == 0:
                # Root category — just clear
                cursor.execute(
                    """
                    UPDATE normalized_categories
                    SET nutriscore_category_type_explicit = FALSE,
                        nutriscore_category_type = NULL
                    WHERE category_id = %s
                    """,
                    (category_id,)
                )
            # Get the new (inherited) type
            cursor.execute(
                "SELECT nutriscore_category_type FROM normalized_categories WHERE category_id = %s",
                (category_id,)
            )
            row = cursor.fetchone()
            new_type = row['nutriscore_category_type'] if row else None

            # Cascade to non-explicit descendants
            cursor.execute(
                """
                WITH RECURSIVE descendants AS (
                    SELECT category_id
                    FROM normalized_categories
                    WHERE parent_category_id = %s
                    UNION ALL
                    SELECT nc.category_id
                    FROM normalized_categories nc
                    JOIN descendants d ON nc.parent_category_id = d.category_id
                )
                UPDATE normalized_categories
                SET nutriscore_category_type = %s
                WHERE category_id IN (SELECT category_id FROM descendants)
                  AND (nutriscore_category_type_explicit IS NOT TRUE)
                """,
                (category_id, new_type)
            )
        self.connection.commit()

    def set_product_hidden(self, product_id: int, is_hidden: bool) -> bool:
        """Set the is_hidden flag on a product and immediately insert a price_history row."""
        self._ensure_connection()
        try:
            with self.connection.cursor() as cursor:
                # Update the flag
                cursor.execute(
                    "UPDATE products SET is_hidden = %s, updated_at = CURRENT_TIMESTAMP WHERE product_id = %s",
                    (is_hidden, product_id)
                )
                # Fetch the latest known price to carry forward
                cursor.execute("""
                    SELECT price FROM product_price_history
                    WHERE product_id = %s
                    ORDER BY recorded_at DESC
                    LIMIT 1
                """, (product_id,))
                row = cursor.fetchone()
                if row:
                    last_price = row[0]
                    cursor.execute("""
                        INSERT INTO product_price_history
                            (product_id, price, is_available, data_source, recorded_at)
                        VALUES (%s, %s, %s, 'visibility_override', CURRENT_TIMESTAMP)
                    """, (product_id, last_price, not is_hidden))
            self.connection.commit()
            return True
        except Exception as e:
            self.connection.rollback()
            return False

    def close(self):
        """Close database connection"""
        if self.connection and not self.connection.closed:
            self.connection.close()
