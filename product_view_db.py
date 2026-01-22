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
            pp.photo_url
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
            COALESCE(nf.nutrition_manual_edit, FALSE) as nutrition_manual_edit
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
            pp.photo_url
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
    
    def close(self):
        """Close database connection"""
        if self.connection and not self.connection.closed:
            self.connection.close()
