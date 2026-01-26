"""
Fiber Estimation Module for Barbora Project

Sample implementation - adapt to your project structure.
Uses category_id (numeric) to look up fiber defaults.

Usage:
    from fiber_estimator_barbora_sample import FiberEstimator
    
    estimator = FiberEstimator()
    fiber, source, should_update, match_type = estimator.estimate_fiber(
        product_name="Pilngraudu makaroni 500g",
        category_id=48,
        current_fiber=None
    )
"""

import json
import os
from typing import Optional, Tuple


class FiberEstimator:
    def __init__(self, config_path: str = "fiber_estimation_config.json"):
        """Load fiber estimation config from JSON file."""
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        self.category_defaults = {
            int(k): v for k, v in config['category_fiber_defaults'].items()
        }
        self.exception_rules = config['exception_rules']
    
    def check_exception_rules(self, product_name: str, category_id: int) -> Tuple[Optional[float], Optional[str]]:
        """
        Check if product matches any exception rules.
        Exception rules override category defaults for specific products.
        
        Returns:
            (fiber_value, reason) if matched, else (None, None)
        """
        product_name_lower = product_name.lower()
        category_id_str = str(category_id)
        
        for rule in self.exception_rules:
            if not category_id_str.startswith(rule["category_id_prefix"]):
                continue
            
            for keyword in rule["keywords"]:
                if keyword.lower() in product_name_lower:
                    return rule["fiber"], rule["reason"]
        
        return None, None
    
    def estimate_fiber(
        self, 
        product_name: str, 
        category_id: int, 
        current_fiber: Optional[float]
    ) -> Tuple[float, str, bool, str]:
        """
        Estimate fiber content for a product.
        
        Args:
            product_name: Product name for exception matching
            category_id: Category ID (numeric)
            current_fiber: Current fiber value from database
            
        Returns:
            tuple of (fiber_value, source_description, should_update, match_type)
            - fiber_value: The fiber amount to use
            - source_description: Explanation of where value came from
            - should_update: Whether database should be updated
            - match_type: 'existing', 'exception', or 'category'
        """
        if current_fiber is not None and current_fiber > 0:
            return current_fiber, "Existing scraped/USDA value", False, "existing"
        
        exception_fiber, exception_reason = self.check_exception_rules(product_name, category_id)
        if exception_fiber is not None:
            return exception_fiber, f"Exception: {exception_reason}", True, "exception"
        
        category_fiber = self.category_defaults.get(category_id)
        if category_fiber is not None:
            return category_fiber, f"Category default for ID {category_id}", True, "category"
        
        return 0.0, "No category match found", False, "none"
    
    def batch_estimate(self, products: list) -> list:
        """
        Estimate fiber for multiple products.
        
        Args:
            products: List of dicts with keys: product_id, name, category_id, fiber
            
        Returns:
            List of dicts with estimation results
        """
        results = []
        for product in products:
            fiber, source, should_update, match_type = self.estimate_fiber(
                product_name=product.get('name', ''),
                category_id=product.get('category_id', 0),
                current_fiber=product.get('fiber')
            )
            
            if should_update and fiber > 0:
                results.append({
                    'product_id': product['product_id'],
                    'name': product['name'],
                    'category_id': product['category_id'],
                    'old_fiber': product.get('fiber'),
                    'new_fiber': fiber,
                    'source': source,
                    'match_type': match_type
                })
        
        return results


def apply_fiber_estimates_to_db(conn, estimates: list, recalculate_nutriscore: bool = True):
    """
    Apply fiber estimates to database.
    
    Args:
        conn: Database connection (psycopg2)
        estimates: List from batch_estimate()
        recalculate_nutriscore: Whether to recalculate Nutri-Score after update
    """
    cursor = conn.cursor()
    updated = 0
    
    for est in estimates:
        try:
            cursor.execute("""
                UPDATE nutritionfacts 
                SET fiber = %s, is_fiber_correct = FALSE
                WHERE product_id = %s
            """, (est['new_fiber'], est['product_id']))
            updated += 1
        except Exception as e:
            print(f"Error updating {est['product_id']}: {e}")
    
    conn.commit()
    cursor.close()
    
    print(f"Updated {updated} products with fiber estimates")
    
    if recalculate_nutriscore:
        print("Remember to recalculate Nutri-Scores for updated products!")
    
    return updated


def get_products_missing_fiber(conn) -> list:
    """
    Get all products with missing fiber data.
    
    Args:
        conn: Database connection (psycopg2)
        
    Returns:
        List of product dicts
    """
    cursor = conn.cursor()
    cursor.execute("""
        SELECT 
            p.product_id,
            p.name,
            p.category_id,
            nf.fiber
        FROM products p
        JOIN nutritionfacts nf ON p.product_id = nf.product_id
        WHERE (nf.fiber IS NULL OR nf.fiber = 0)
          AND nf.energy_kj IS NOT NULL
        ORDER BY p.name
    """)
    
    columns = [desc[0] for desc in cursor.description]
    products = [dict(zip(columns, row)) for row in cursor.fetchall()]
    cursor.close()
    
    return products


if __name__ == "__main__":
    estimator = FiberEstimator()
    
    test_products = [
        {"product_id": 1, "name": "Pilngraudu makaroni 500g", "category_id": 48, "fiber": None},
        {"product_id": 2, "name": "Baltā rīsi 1kg", "category_id": 47, "fiber": None},
        {"product_id": 3, "name": "Tumšā šokolāde 85% 100g", "category_id": 36, "fiber": None},
        {"product_id": 4, "name": "Piens 2.5% 1L", "category_id": 108, "fiber": None},
        {"product_id": 5, "name": "Pilngraudu cepumi 200g", "category_id": 174, "fiber": None},
    ]
    
    print("Testing fiber estimation:")
    print("-" * 80)
    
    for product in test_products:
        fiber, source, should_update, match_type = estimator.estimate_fiber(
            product['name'], product['category_id'], product['fiber']
        )
        print(f"{product['name'][:40]:40} | cat:{product['category_id']:3} | "
              f"fiber:{fiber:4.1f}g | {match_type:10} | {source[:30]}")
    
    print("-" * 80)
    print("\nBatch estimate results:")
    results = estimator.batch_estimate(test_products)
    for r in results:
        print(f"  {r['name'][:40]} -> {r['new_fiber']}g ({r['match_type']})")
