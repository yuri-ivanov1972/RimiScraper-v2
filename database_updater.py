#!/usr/bin/env python3
"""
Database Updater - Core functionality for updating PRODUCTS_DB_URL database
Handles product CRUD operations, nutrition data, price history, and photos
"""
import os
import time
import psycopg2
import psycopg2.extras
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timezone
import re
from decimal import Decimal
from nutriscore_calculator import NutriscoreCalculator
from ingredient_processor import IngredientProcessor

class DatabaseUpdater:
    """Core database updater for PRODUCTS_DB_URL database"""
    
    def __init__(self, status_callback=None):
        # Use the same database configuration as EnhancedDatabaseUpdater
        from database_config import db_config
        self.status_callback = status_callback or (lambda x: None)
        self.db_config = db_config
        self.db_url = db_config.products_db_url
        
        self.nutri_calculator = NutriscoreCalculator()
        self.ingredient_processor = None
        self.conn = None
        self._connect()
    
    def _connect(self):
        """Establish database connection with retry logic"""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                if self.conn:
                    self.conn.close()
                self.conn = psycopg2.connect(self.db_url)
                self.conn.autocommit = False
                
                # Log database identity for debugging (same as EnhancedDatabaseUpdater)
                cursor = self.conn.cursor()
                cursor.execute("SELECT current_database(), inet_server_addr(), inet_server_port(), version() LIMIT 1")
                db_info = cursor.fetchone()
                cursor.close()
                
                db_mode = "DEVELOPMENT (DATABASE_URL)" if self.db_config.is_development else "PRODUCTION (PRODUCTS_DB_URL)"
                self.status_callback(f"Connected to {db_mode} database: {db_info[0]} @ {db_info[1] if db_info[1] else 'local'}:{db_info[2] if db_info[2] else 'default'}")
                return
            except Exception as e:
                if attempt < max_retries - 1:
                    self.status_callback(f"Connection attempt {attempt + 1} failed, retrying...")
                    time.sleep(1)
                else:
                    raise Exception(f"Database connection failed after {max_retries} attempts: {str(e)}")

    def _ensure_connection(self):
        """Ensure database connection is active"""
        try:
            if not self.conn or self.conn.closed:
                self._connect()
            else:
                # Test connection with a simple query
                with self.conn.cursor() as cursor:
                    cursor.execute("SELECT 1")
        except Exception:
            self._connect()
    
    def _execute_query(self, query: str, params: Tuple = None, fetch: bool = False) -> Optional[List]:
        """Execute query with robust connection handling"""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                self._ensure_connection()
                with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                    cursor.execute(query, params)
                    if fetch:
                        return cursor.fetchall()
                    return None
            except (psycopg2.OperationalError, psycopg2.InterfaceError) as e:
                if attempt < max_retries - 1:
                    self.status_callback(f"Query attempt {attempt + 1} failed due to connection issue, reconnecting...")
                    self._connect()
                    time.sleep(0.5)
                else:
                    raise Exception(f"Query execution failed after {max_retries} attempts: {str(e)}")
            except Exception as e:
                if self.conn:
                    try:
                        self.conn.rollback()
                    except:
                        pass
                raise Exception(f"Query execution failed: {str(e)}")
    
    def get_product_by_sku(self, sku: str) -> Optional[Dict]:
        """Get existing product by SKU"""
        query = "SELECT * FROM products WHERE sku = %s"
        result = self._execute_query(query, (sku,), fetch=True)
        return dict(result[0]) if result else None
    
    def add_new_product(self, product_data: Dict) -> int:
        """
        Add new product to database with all related data
        
        Args:
            product_data: Dictionary containing product information
            
        Returns:
            product_id of newly created product
        """
        try:
            # Extract basic product info
            sku = product_data['sku']
            name = product_data['name']
            rimi_url = product_data.get('url', '')
            category_id = product_data.get('category_id', 1)  # Default category
            price = product_data.get('price', '')
            
            # Parse quantity if available
            quantity_value, quantity_unit = self._parse_quantity(name)
            self.status_callback(f"Extracted quantity: {quantity_value} {quantity_unit} from '{name[:50]}'")
            
            self.status_callback(f"Creating or updating product: {sku} - {name[:50]}")
            
            # UPSERT into products table (handles concurrent inserts gracefully)
            product_query = """
                INSERT INTO products (sku, name, rimi_url, category_id, quantity_value, quantity_unit)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (sku) DO UPDATE SET
                    name = COALESCE(EXCLUDED.name, products.name),
                    category_id = COALESCE(EXCLUDED.category_id, products.category_id),
                    rimi_url = COALESCE(EXCLUDED.rimi_url, products.rimi_url),
                    quantity_value = COALESCE(EXCLUDED.quantity_value, products.quantity_value),
                    quantity_unit = COALESCE(EXCLUDED.quantity_unit, products.quantity_unit),
                    updated_at = NOW()
                RETURNING product_id
            """
            
            result = self._execute_query(
                product_query,
                (sku, name, rimi_url, category_id, quantity_value, quantity_unit),
                fetch=True
            )
            
            product_id = result[0]['product_id']
            
            # Add initial price history record with new price fields
            if price and price != 'N/A':
                price_decimal = self._parse_price(price)
                if price_decimal is not None:
                    # Parse new price fields from product_data
                    price_per_unit = None
                    price_per_unit_type = product_data.get('price_per_unit_type')
                    discount_price = None
                    discount_price_per_unit = None
                    
                    if product_data.get('price_per_unit'):
                        try:
                            price_per_unit = Decimal(str(product_data['price_per_unit']))
                        except:
                            pass
                    
                    if product_data.get('discount_price'):
                        try:
                            discount_price = self._parse_price(product_data['discount_price'])
                        except:
                            pass
                    
                    if product_data.get('discount_price_per_unit'):
                        try:
                            discount_price_per_unit = Decimal(str(product_data['discount_price_per_unit']))
                        except:
                            pass
                    
                    # Use is_available from product_data (defaults to True if not provided)
                    is_available = product_data.get('is_available', True)
                    
                    self._add_price_history_record(
                        product_id, price_decimal, is_available, 'rimi_scraper',
                        price_per_unit=price_per_unit, price_per_unit_type=price_per_unit_type,
                        discount_price=discount_price, discount_price_per_unit=discount_price_per_unit
                    )
            
            self.conn.commit()
            self.status_callback(f"Successfully created/updated product {sku} with ID {product_id}")
            return product_id
            
        except Exception as e:
            self.conn.rollback()
            raise Exception(f"Failed to add product {sku}: {str(e)}")
    
    def add_nutrition_data(self, product_id: int, nutrition_data: Dict, category_code: str = None) -> bool:
        """
        Add nutrition data for a product with conditional nutri-score calculation
        
        Args:
            product_id: ID of the product
            nutrition_data: Dictionary with nutrition information
            category_code: Product category for nutri-score calculation
            
        Returns:
            True if successful
        """
        try:
            # Extract nutrition values with safe conversion - map from extracted data to schema fields
            ingredients_text = nutrition_data.get('ingredients', '')
            energy_kcal = float(nutrition_data.get('energy_kcal', 0)) if nutrition_data.get('energy_kcal') else None
            energy_kj = float(nutrition_data.get('energy_kj', 0)) if nutrition_data.get('energy_kj') else None
            
            # Map extracted field names to database field names
            fat_total = float(nutrition_data.get('fat_total', 0)) if nutrition_data.get('fat_total') else None
            fat_saturated = float(nutrition_data.get('fat_saturated', 0)) if nutrition_data.get('fat_saturated') else None
            carbs_total = float(nutrition_data.get('carbs_total', 0)) if nutrition_data.get('carbs_total') else None
            carbs_sugars = float(nutrition_data.get('carbs_sugars', 0)) if nutrition_data.get('carbs_sugars') else None
            protein = float(nutrition_data.get('protein', 0)) if nutrition_data.get('protein') else None
            salt = float(nutrition_data.get('salt', 0)) if nutrition_data.get('salt') else None
            fiber = float(nutrition_data.get('fiber', 0)) if nutrition_data.get('fiber') else None
            
            # Determine is_fiber_correct based on actual fiber source
            # True = scraped from Rimi / USDA / manual entry (reliable)
            # False = missing/zero fiber (needs estimation or verification)
            # Note: Estimated fiber still gets is_fiber_correct=False until manually verified
            scraped_fiber = nutrition_data.get('fiber')
            has_scraped_fiber = scraped_fiber is not None and float(scraped_fiber) > 0
            is_fiber_correct = has_scraped_fiber  # True only if fiber was actually scraped
            
            # Estimate fiber if not scraped (for new products)
            if (fiber is None or fiber == 0) and category_code:
                try:
                    from fiber_estimator import estimate_fiber
                    # Try to get product name - may not be in nutrition_data
                    product_name = nutrition_data.get('product_name', nutrition_data.get('name', ''))
                    estimated_fiber, source, should_update, match_type = estimate_fiber(product_name, category_code, fiber)
                    if should_update and estimated_fiber > 0:
                        fiber = estimated_fiber
                        # Estimated fiber keeps is_fiber_correct=False until manually verified
                        self.status_callback(f"Estimated fiber: {fiber}g ({source}) [{match_type}]")
                except Exception as e:
                    self.status_callback(f"Fiber estimation failed: {e}")
            
            # Check if product already has nutri-score
            existing_nutri_query = """
                SELECT nutri_score_grade FROM nutritionfacts WHERE product_id = %s
            """
            existing_nutri = self._execute_query(existing_nutri_query, (product_id,), fetch=True)
            has_existing_nutriscore = (existing_nutri and 
                                     len(existing_nutri) > 0 and 
                                     existing_nutri[0].get('nutri_score_grade') is not None and 
                                     existing_nutri[0].get('nutri_score_grade') != '')
            
            # Calculate nutri-score if missing and we have sufficient data
            nutri_score_grade = None
            nutri_score_points = None
            
            if not has_existing_nutriscore and energy_kj and energy_kj > 0 and carbs_sugars is not None and fat_saturated is not None and salt is not None and protein is not None:
                nutri_result = self.nutri_calculator.calculate_single_product(
                    energy_kj=energy_kj,
                    sugars=carbs_sugars,
                    saturated_fat=fat_saturated,
                    salt=salt,
                    protein=protein,
                    fiber=int(fiber) if fiber else 0,
                    total_fat=fat_total,
                    category_code=category_code
                )
                
                if nutri_result['success']:
                    nutri_score_grade = nutri_result['grade']
                    nutri_score_points = nutri_result['score']
                    self.status_callback(f"Calculated nutri-score: {nutri_score_grade} ({nutri_score_points} points)")
            elif has_existing_nutriscore:
                self.status_callback(f"Product {product_id} already has nutri-score, skipping calculation")
            else:
                self.status_callback(f"Insufficient nutrition data for nutri-score calculation (missing: energy_kj={energy_kj}, sugars={carbs_sugars}, sat_fat={fat_saturated}, salt={salt}, protein={protein})")
            
            # Check if product is manually edited - skip nutrition update if so
            existing_manual_edit = self._execute_query(
                "SELECT nutrition_manual_edit FROM nutritionfacts WHERE product_id = %s",
                (product_id,),
                fetch=True
            )
            if existing_manual_edit and existing_manual_edit[0].get('nutrition_manual_edit'):
                self.status_callback(f"Skipping nutrition update for product {product_id} - marked as manually edited")
                return True
            
            # Insert nutrition data using correct table schema from export
            nutrition_query = """
                INSERT INTO nutritionfacts 
                (product_id, ingredients_text, energy_kcal, energy_kj, fat_total, fat_saturated,
                 carbs_total, carbs_sugars, protein, salt, fiber, nutri_score_grade, nutri_score_points,
                 data_source_date, is_fiber_correct)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (product_id) DO UPDATE SET
                    ingredients_text = EXCLUDED.ingredients_text,
                    energy_kcal = EXCLUDED.energy_kcal,
                    energy_kj = EXCLUDED.energy_kj,
                    fat_total = EXCLUDED.fat_total,
                    fat_saturated = EXCLUDED.fat_saturated,
                    carbs_total = EXCLUDED.carbs_total,
                    carbs_sugars = EXCLUDED.carbs_sugars,
                    protein = EXCLUDED.protein,
                    salt = EXCLUDED.salt,
                    fiber = EXCLUDED.fiber,
                    nutri_score_grade = EXCLUDED.nutri_score_grade,
                    nutri_score_points = EXCLUDED.nutri_score_points,
                    data_source_date = EXCLUDED.data_source_date,
                    is_fiber_correct = EXCLUDED.is_fiber_correct
                WHERE NOT COALESCE(nutritionfacts.nutrition_manual_edit, FALSE)
            """
            
            self._execute_query(nutrition_query, (
                product_id, ingredients_text, energy_kcal, energy_kj, fat_total, fat_saturated,
                carbs_total, carbs_sugars, protein, salt, fiber, nutri_score_grade, nutri_score_points,
                datetime.now(timezone.utc), is_fiber_correct
            ))
            
            # Commit the transaction
            self.conn.commit()
            self.status_callback(f"Added nutrition data for product ID {product_id}")
            return True
            
        except Exception as e:
            raise Exception(f"Failed to add nutrition data: {str(e)}")
    
    def process_product_ingredients(self, sku: str, ingredients_text: str) -> bool:
        """
        Process ingredients for a product using ingredient processor
        
        Args:
            sku: Product SKU
            ingredients_text: Raw ingredients text
            
        Returns:
            True if successful
        """
        try:
            if not ingredients_text or ingredients_text.strip() == '':
                self.status_callback(f"No ingredients to process for product {sku}")
                return True
            
            # Initialize ingredient processor if not already done
            if not self.ingredient_processor:
                self.ingredient_processor = IngredientProcessor(self.status_callback)
            
            # Process ingredients
            result = self.ingredient_processor.process_product_ingredients(sku, ingredients_text)
            
            if result.get('processed', 0) > 0:
                self.status_callback(f"Processed {result['processed']} ingredients for product {sku}")
                return True
            else:
                self.status_callback(f"No ingredients processed for product {sku}")
                return True
                
        except Exception as e:
            self.status_callback(f"Error processing ingredients for {sku}: {str(e)}")
            return False
    
    def add_product_photos(self, product_id: int, photo_urls: List[str]) -> bool:
        """
        Add product photos to productphotos table with enhanced error handling
        
        Args:
            product_id: Product ID to associate photos with
            photo_urls: List of photo URLs (typically one primary photo)
            
        Returns:
            True if successful, False if failed
        """
        try:
            if not photo_urls:
                self.status_callback(f"No photos to save for product ID {product_id}")
                return True
            
            if not isinstance(photo_urls, list):
                self.status_callback(f"Failed to save in database: photo_urls must be a list, got {type(photo_urls)}")
                return False
            
            self.status_callback(f"Attempting to save {len(photo_urls)} photo(s) for product ID {product_id}")
            
            # Ensure database connection
            self._ensure_connection()
            
            # Clear existing photos for this product
            try:
                delete_query = "DELETE FROM productphotos WHERE product_id = %s"
                self._execute_query(delete_query, (product_id,))
                self.status_callback(f"Cleared existing photos for product ID {product_id}")
            except Exception as e:
                self.status_callback(f"Failed to save in database: Error clearing existing photos - {str(e)}")
                return False
            
            # Add new photos (primary photo first)
            photos_saved = 0
            for i, url in enumerate(photo_urls):
                if not url or not isinstance(url, str):
                    self.status_callback(f"Skipping invalid photo URL at index {i}: {repr(url)}")
                    continue
                
                is_primary = (i == 0)  # First photo is primary
                
                try:
                    insert_query = """
                        INSERT INTO productphotos (product_id, photo_url, is_primary) 
                        VALUES (%s, %s, %s)
                    """
                    self._execute_query(insert_query, (product_id, url.strip(), is_primary))
                    
                    photo_status = "primary" if is_primary else "secondary"
                    self.status_callback(f"Successfully saved {photo_status} photo: {url}")
                    photos_saved += 1
                    
                except Exception as e:
                    self.status_callback(f"Failed to save in database: Error inserting photo {i+1} ({url}) - {str(e)}")
                    # Continue trying to save other photos rather than failing completely
            
            if photos_saved == 0:
                self.status_callback(f"Failed to save in database: No valid photos could be saved for product ID {product_id}")
                return False
            
            # Commit the transaction
            try:
                self.conn.commit()
                self.status_callback(f"Successfully committed {photos_saved} photo(s) to database for product ID {product_id}")
                return True
            except Exception as e:
                self.status_callback(f"Failed to save in database: Error committing transaction - {str(e)}")
                try:
                    self.conn.rollback()
                    self.status_callback("Database transaction rolled back")
                except:
                    pass
                return False
            
        except Exception as e:
            self.status_callback(f"Failed to save in database: Unexpected error in add_product_photos - {str(e)}")
            try:
                if self.conn:
                    self.conn.rollback()
            except:
                pass
            return False
    
    def update_product_price(self, sku: str, price: str, is_available: bool = True,
                              price_per_unit: Optional[str] = None, price_per_unit_type: Optional[str] = None,
                              discount_price: Optional[str] = None, discount_price_per_unit: Optional[str] = None) -> bool:
        """Update product price and availability with optional price-per-unit and discount data"""
        try:
            # Get product ID
            product = self.get_product_by_sku(sku)
            if not product:
                self.status_callback(f"Product {sku} not found for price update")
                return False
            
            product_id = product['product_id']
            
            # Parse price
            price_decimal = self._parse_price(price)
            if price_decimal is None:
                self.status_callback(f"Invalid price format: {price}")
                return False
            
            # Parse new price fields
            price_per_unit_decimal = None
            discount_price_decimal = None
            discount_price_per_unit_decimal = None
            
            if price_per_unit:
                try:
                    price_per_unit_decimal = Decimal(str(price_per_unit))
                except:
                    pass
            
            if discount_price:
                discount_price_decimal = self._parse_price(discount_price)
            
            if discount_price_per_unit:
                try:
                    discount_price_per_unit_decimal = Decimal(str(discount_price_per_unit))
                except:
                    pass
            
            # Override availability for hidden products
            if product.get('is_hidden'):
                is_available = False
                self.status_callback(f"Product {sku} is hidden — forcing is_available=False")

            # Add price history record with new fields
            self._add_price_history_record(
                product_id, price_decimal, is_available, 'rimi_scraper',
                price_per_unit=price_per_unit_decimal, price_per_unit_type=price_per_unit_type,
                discount_price=discount_price_decimal, discount_price_per_unit=discount_price_per_unit_decimal
            )
            
            self.conn.commit()
            self.status_callback(f"Updated price for {sku}: {price} (available: {is_available})")
            return True
            
        except Exception as e:
            self.conn.rollback()
            raise Exception(f"Failed to update price for {sku}: {str(e)}")
    
    def mark_product_unavailable(self, sku: str) -> bool:
        """Mark product as unavailable"""
        try:
            product = self.get_product_by_sku(sku)
            if not product:
                return False
            
            product_id = product['product_id']
            
            # Get last known price
            last_price_query = """
                SELECT price FROM product_price_history 
                WHERE product_id = %s 
                ORDER BY recorded_at DESC 
                LIMIT 1
            """
            
            result = self._execute_query(last_price_query, (product_id,), fetch=True)
            last_price = result[0]['price'] if result else Decimal('0.00')
            
            # Add unavailable record
            self._add_price_history_record(product_id, last_price, False, 'rimi_scraper')
            
            self.conn.commit()
            self.status_callback(f"Marked product {sku} as unavailable")
            return True
            
        except Exception as e:
            self.conn.rollback()
            raise Exception(f"Failed to mark {sku} unavailable: {str(e)}")
    
    def _add_price_history_record(self, product_id: int, price: Decimal, is_available: bool, data_source: str,
                                    price_per_unit: Optional[Decimal] = None, price_per_unit_type: Optional[str] = None,
                                    discount_price: Optional[Decimal] = None, discount_price_per_unit: Optional[Decimal] = None):
        """Add price history record with optional discount and price-per-unit data"""
        # Use past timestamp to avoid constraint issues - subtract 1 minute to ensure it's in the past
        from datetime import timedelta
        current_time = datetime.now(timezone.utc) - timedelta(minutes=1)
        
        price_query = """
            INSERT INTO product_price_history (
                product_id, price, currency, is_available, recorded_at, data_source,
                price_per_unit, price_per_unit_type, discount_price, discount_price_per_unit
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        
        self._execute_query(price_query, (
            product_id,
            price,
            'EUR',
            is_available,
            current_time,
            data_source,
            price_per_unit,
            price_per_unit_type,
            discount_price,
            discount_price_per_unit
        ))
    
    def _parse_price(self, price_str: str) -> Optional[Decimal]:
        """Parse price string to Decimal"""
        if not price_str or price_str == 'N/A':
            return None
        
        try:
            # Remove currency symbols and whitespace
            clean_price = re.sub(r'[€$£]', '', price_str).strip()
            # Replace comma with dot for decimal
            clean_price = clean_price.replace(',', '.')
            # Remove any remaining non-numeric characters except dots
            clean_price = re.sub(r'[^\d.]', '', clean_price)
            return Decimal(clean_price)
        except Exception as e:
            self.status_callback(f"Failed to parse price '{price_str}': {str(e)}")
            return None
    
    def _parse_quantity(self, product_name: str) -> Tuple[Optional[Decimal], Optional[str]]:
        """Extract quantity from product name"""
        try:
            name_lower = product_name.lower()

            # Check for multiplier pattern first: e.g. "25x2g", "6x0,33l", "20x1,5g"
            # Matches: multiplier x unit_qty unit  -> total = multiplier * unit_qty
            multiplier_pattern = r'(\d+)\s*[xX×]\s*(\d+(?:[.,]\d+)?)\s*(g|kg|ml|l)\b'
            m = re.search(multiplier_pattern, name_lower)
            if m:
                multiplier = Decimal(m.group(1))
                unit_qty = Decimal(m.group(2).replace(',', '.'))
                unit = m.group(3).lower()
                return multiplier * unit_qty, unit

            # Look for patterns like "500g", "1.5L", "250ml", "10 gb.", etc.
            # Added Latvian units: gb (gabali = pieces), gab (gabali)
            quantity_pattern = r'(\d+(?:[.,]\d+)?)\s*(g|kg|ml|l|pcs|pc|gab|gb)\.?\b'
            match = re.search(quantity_pattern, name_lower)

            if match:
                value = Decimal(match.group(1).replace(',', '.'))
                unit = match.group(2).lower()
                # Normalize Latvian units to standard abbreviations
                if unit in ['gb']:
                    unit = 'gab'  # Keep Latvian abbreviation for pieces
                return value, unit

            # Check for products sold by weight (ending with " kg")
            if name_lower.strip().endswith(' kg'):
                return None, 'kg'  # Variable weight, no fixed quantity

            return None, None
        except:
            return None, None
    
    def get_update_statistics(self) -> Dict:
        """Get statistics about recent updates"""
        try:
            stats = {}
            
            # Total products
            total_query = "SELECT COUNT(*) as count FROM products"
            result = self._execute_query(total_query, fetch=True)
            stats['total_products'] = result[0]['count']
            
            # Products with nutrition data
            nutrition_query = "SELECT COUNT(*) as count FROM nutritionfacts"
            result = self._execute_query(nutrition_query, fetch=True)
            stats['products_with_nutrition'] = result[0]['count']
            
            # Recent price updates (last 24 hours)
            recent_price_query = """
                SELECT COUNT(*) as count FROM product_price_history 
                WHERE created_at > NOW() - INTERVAL '24 hours'
            """
            result = self._execute_query(recent_price_query, fetch=True)
            stats['recent_price_updates'] = result[0]['count']
            
            # Available vs unavailable products
            availability_query = """
                SELECT 
                    SUM(CASE WHEN is_available THEN 1 ELSE 0 END) as available,
                    SUM(CASE WHEN NOT is_available THEN 1 ELSE 0 END) as unavailable
                FROM (
                    SELECT DISTINCT ON (product_id) product_id, is_available
                    FROM product_price_history
                    ORDER BY product_id, recorded_at DESC
                ) latest
            """
            result = self._execute_query(availability_query, fetch=True)
            if result and result[0]:
                stats['available_products'] = result[0]['available'] or 0
                stats['unavailable_products'] = result[0]['unavailable'] or 0
            
            return stats
            
        except Exception as e:
            self.status_callback(f"Error getting statistics: {str(e)}")
            return {}
    
    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()
            self.status_callback("Database connection closed")