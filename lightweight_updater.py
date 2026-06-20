"""
Lightweight updater for existing products - updates price/availability without detail page scraping
"""

import os
import psycopg2
from typing import Optional, Dict
import re


class LightweightUpdater:
    """
    Lightweight product updater that uses listing-level data (price) without detail page scraping.
    Used in incremental mode to quickly update existing products.
    """
    
    def __init__(self, db_connection=None):
        """
        Initialize lightweight updater
        
        Args:
            db_connection: Optional database connection (will create if not provided)
        """
        self.db_connection = db_connection
        self._should_close_connection = db_connection is None
    
    def _get_connection(self):
        """Get database connection (create if needed)"""
        if self.db_connection:
            return self.db_connection
        return psycopg2.connect(os.environ['DATABASE_URL'])
    
    def _parse_price(self, price_str: str) -> Optional[float]:
        """
        Parse price string to float
        
        Args:
            price_str: Price string like "€2.99" or "2.99€"
        
        Returns:
            Float price or None if parsing fails
        """
        if not price_str:
            return None
        
        try:
            # Remove currency symbols and whitespace
            cleaned = re.sub(r'[€$\s]', '', price_str)
            # Replace comma with dot for decimal
            cleaned = cleaned.replace(',', '.')
            return float(cleaned)
        except (ValueError, AttributeError):
            return None
    
    def update_from_listing_data(self, sku: str, listing_data: Dict) -> Dict:
        """
        Update existing product using listing-level data (price only, no detail scraping)
        Note: Prices are stored in product_price_history table, not products table
        
        Args:
            sku: Product SKU
            listing_data: Dictionary with 'price', 'price_per_unit', 'price_per_unit_type',
                         'discount_price', 'discount_price_per_unit', 'is_available' and optionally 'name' from listing
        
        Returns:
            Dictionary with update results
        """
        conn = None
        try:
            conn = self._get_connection()
            cur = conn.cursor()
            
            # Parse price
            price_str = listing_data.get('price', '')
            price = self._parse_price(price_str)
            
            # Parse new price fields
            price_per_unit_str = listing_data.get('price_per_unit')
            price_per_unit = float(price_per_unit_str) if price_per_unit_str else None
            price_per_unit_type = listing_data.get('price_per_unit_type')
            
            discount_price_str = listing_data.get('discount_price')
            discount_price = self._parse_price(discount_price_str) if discount_price_str else None
            
            discount_price_per_unit_str = listing_data.get('discount_price_per_unit')
            discount_price_per_unit = float(discount_price_per_unit_str) if discount_price_per_unit_str else None
            
            # Get availability from listing data (defaults to True if not provided for backward compatibility)
            is_available = listing_data.get('is_available', True)
            
            # If price is None but product is unavailable, use last known price from DB
            # (product_price_history.price is NOT NULL, so we cannot store NULL)
            if price is None and not is_available:
                pass  # price will be resolved after we fetch old_price below
            elif price is None:
                return {
                    'success': False,
                    'sku': sku,
                    'error': f'Could not parse price: {price_str}'
                }
            
            # Get current product data and latest price from price_history (including discount fields)
            cur.execute("""
                SELECT 
                    p.product_id,
                    p.name,
                    pph.price,
                    pph.is_available,
                    pph.price_per_unit,
                    pph.price_per_unit_type,
                    pph.discount_price,
                    pph.discount_price_per_unit
                FROM products p
                LEFT JOIN LATERAL (
                    SELECT price, is_available, recorded_at,
                           price_per_unit, price_per_unit_type, discount_price, discount_price_per_unit
                    FROM product_price_history
                    WHERE product_id = p.product_id
                    ORDER BY recorded_at DESC
                    LIMIT 1
                ) pph ON true
                WHERE p.sku = %s
            """, (sku,))
            
            row = cur.fetchone()
            if not row:
                return {
                    'success': False,
                    'sku': sku,
                    'error': 'Product not found in database'
                }
            
            (product_id, product_name, old_price, old_availability,
             old_price_per_unit, old_price_per_unit_type, old_discount_price, old_discount_price_per_unit) = row
            old_price = float(old_price) if old_price is not None else None
            old_price_per_unit = float(old_price_per_unit) if old_price_per_unit is not None else None
            old_discount_price = float(old_discount_price) if old_discount_price is not None else None
            old_discount_price_per_unit = float(old_discount_price_per_unit) if old_discount_price_per_unit is not None else None

            # Resolve price for unavailable products: carry forward last known price
            # because product_price_history.price is NOT NULL and cannot store NULL
            if price is None and not is_available:
                price = old_price if old_price is not None else 0.0

            # Track changes - compare all price-related fields
            price_changed = (old_price != price) if old_price is not None else True
            
            # Detect availability changes - compare old vs new availability
            availability_changed = (old_availability != is_available) if old_availability is not None else False
            
            # Check if any of the new price fields changed (including NULL transitions)
            price_per_unit_changed = (old_price_per_unit != price_per_unit)
            price_per_unit_type_changed = (old_price_per_unit_type != price_per_unit_type)
            discount_price_changed = (old_discount_price != discount_price)
            discount_price_per_unit_changed = (old_discount_price_per_unit != discount_price_per_unit)
            
            any_price_data_changed = (
                price_changed or availability_changed or
                price_per_unit_changed or price_per_unit_type_changed or
                discount_price_changed or discount_price_per_unit_changed
            )
            
            # Insert new price history record if any price-related data changed
            if any_price_data_changed:
                cur.execute("""
                    INSERT INTO product_price_history (
                        product_id, price, is_available, data_source, recorded_at,
                        price_per_unit, price_per_unit_type, discount_price, discount_price_per_unit
                    )
                    VALUES (%s, %s, %s, 'lightweight_update', CURRENT_TIMESTAMP, %s, %s, %s, %s)
                """, (product_id, price, is_available, price_per_unit, price_per_unit_type, discount_price, discount_price_per_unit))
            
            # Update product timestamp
            cur.execute("""
                UPDATE products
                SET updated_at = CURRENT_TIMESTAMP
                WHERE sku = %s
            """, (sku,))
            
            conn.commit()
            
            return {
                'success': True,
                'sku': sku,
                'price_changed': price_changed,
                'old_price': old_price,
                'new_price': price,
                'availability_changed': availability_changed,
                'discount_changed': discount_price_changed,
                'price_per_unit_changed': price_per_unit_changed,
                'update_type': 'lightweight'
            }
            
        except Exception as e:
            if conn:
                conn.rollback()
            return {
                'success': False,
                'sku': sku,
                'error': str(e)
            }
        finally:
            if self._should_close_connection and conn:
                conn.close()
    
    def batch_update_from_listing(self, listing_products: Dict[str, Dict]) -> Dict:
        """
        Update multiple products from listing data
        
        Args:
            listing_products: Dictionary mapping SKU to listing data
        
        Returns:
            Summary of batch update results
        """
        results = {
            'total': len(listing_products),
            'successful': 0,
            'failed': 0,
            'price_changes': 0,
            'availability_changes': 0,
            'errors': []
        }
        
        for sku, listing_data in listing_products.items():
            update_result = self.update_from_listing_data(sku, listing_data)
            
            if update_result['success']:
                results['successful'] += 1
                if update_result.get('price_changed'):
                    results['price_changes'] += 1
                if update_result.get('availability_changed'):
                    results['availability_changes'] += 1
            else:
                results['failed'] += 1
                results['errors'].append({
                    'sku': sku,
                    'error': update_result.get('error')
                })
        
        return results


if __name__ == "__main__":
    # Quick test
    updater = LightweightUpdater()
    
    test_data = {
        'sku': '123456',
        'price': '€2.99',
        'name': 'Test Product'
    }
    
    result = updater.update_from_listing_data('123456', test_data)
    print(f"Update result: {result}")
