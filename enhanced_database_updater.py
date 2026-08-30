"""
Enhanced Database Updater - Fixes corrupted data by force-updating all fields
Handles proper data overwriting for products with partial or corrupted information
"""

import psycopg2
import psycopg2.extras
import os
from typing import Dict, List, Optional, Tuple
from decimal import Decimal
import re
import time
from brand_producer import upsert_brand_producer

class EnhancedDatabaseUpdater:
    """Enhanced database updater with forced update capabilities for corrupted data"""
    
    def __init__(self, status_callback=None):
        from database_config import db_config
        self.status_callback = status_callback or (lambda msg: print(msg))
        self.conn = None
        self.db_config = db_config
        self.products_db_url = db_config.products_db_url
        
        self._connect()
    
    def _connect(self):
        """Establish database connection with retry logic"""
        max_attempts = 3
        for attempt in range(max_attempts):
            try:
                self.conn = psycopg2.connect(
                    self.products_db_url,
                    cursor_factory=psycopg2.extras.RealDictCursor
                )
                self.conn.autocommit = False
                
                # Log database identity for debugging
                cursor = self.conn.cursor()
                cursor.execute("SELECT current_database(), inet_server_addr(), inet_server_port(), version() LIMIT 1")
                db_info = cursor.fetchone()
                cursor.close()
                
                db_mode = "DEVELOPMENT (DATABASE_URL)" if self.db_config.is_development else "PRODUCTION (PRODUCTS_DB_URL)"
                self.status_callback(f"Connected to {db_mode} database: {db_info['current_database']} @ {db_info.get('inet_server_addr', 'local')}:{db_info.get('inet_server_port', 'default')}")
                return
            except Exception as e:
                if attempt < max_attempts - 1:
                    self.status_callback(f"Database connection attempt {attempt + 1} failed, retrying...")
                    time.sleep(2 ** attempt)
                else:
                    raise Exception(f"Failed to connect to database after {max_attempts} attempts: {str(e)}")
    
    def _ensure_connection(self):
        """Ensure database connection is active"""
        try:
            if self.conn is None or self.conn.closed:
                self._connect()
            else:
                # Test connection
                cursor = self.conn.cursor()
                cursor.execute("SELECT 1")
                cursor.close()
        except Exception:
            self._connect()
    
    def _execute_query(self, query: str, params: Tuple = None, fetch: bool = False):
        """Execute query with robust connection handling"""
        self._ensure_connection()
        
        max_attempts = 3
        for attempt in range(max_attempts):
            try:
                cursor = self.conn.cursor()
                cursor.execute(query, params)
                
                if fetch:
                    result = cursor.fetchall()
                    cursor.close()
                    return result
                else:
                    cursor.close()
                    # Commit write operations (INSERT, UPDATE, DELETE)
                    if any(keyword in query.upper() for keyword in ['INSERT', 'UPDATE', 'DELETE']):
                        self.conn.commit()
                        self.status_callback("✓ Database commit succeeded")
                    return None
                    
            except Exception as e:
                if cursor:
                    cursor.close()
                
                if "connection" in str(e).lower() and attempt < max_attempts - 1:
                    self.status_callback(f"Connection error, reconnecting (attempt {attempt + 1})")
                    self._connect()
                    continue
                else:
                    if self.conn:
                        try:
                            self.conn.rollback()
                        except:
                            pass
                    raise Exception(f"Query execution failed: {str(e)}")
    
    def force_update_product_data(self, sku: str, product_data: Dict, force_overwrite: bool = True, is_new_product: bool = False) -> bool:
        """
        Force update product data, overwriting existing corrupted/NULL values
        
        Args:
            sku: Product SKU
            product_data: Complete product data to update
            force_overwrite: Whether to overwrite existing non-NULL values
            is_new_product: Whether this product was newly created in current session (prevents dual price history)
            
        Returns:
            True if successful
        """
        try:
            self.status_callback(f"Force updating product data for SKU: {sku}")
            
            # Get existing product
            existing_product = self.get_product_by_sku(sku)
            if not existing_product:
                self.status_callback(f"Product {sku} not found - cannot force update")
                return False
            
            product_id = existing_product['product_id']

            # Prepare update fields
            update_fields = []
            update_values = []
            
            # Always update rimi_url if provided (fixes NULL urls)
            if 'rimi_url' in product_data and product_data['rimi_url']:
                update_fields.append("rimi_url = %s")
                update_values.append(product_data['rimi_url'])
                self.status_callback(f"Updating rimi_url: {product_data['rimi_url']}")
            
            # Always update category_id if provided (fixes wrong categories)
            if 'category_id' in product_data and product_data['category_id']:
                update_fields.append("category_id = %s")
                update_values.append(product_data['category_id'])
                self.status_callback(f"Updating category_id: {product_data['category_id']}")
            
            # Update name if provided and different
            if 'name' in product_data and product_data['name']:
                if force_overwrite or not existing_product.get('name'):
                    update_fields.append("name = %s")
                    update_values.append(product_data['name'])
                    self.status_callback(f"Updating name: {product_data['name'][:50]}...")
            
            # Update quantity fields if provided
            if 'quantity_value' in product_data:
                update_fields.append("quantity_value = %s")
                update_values.append(product_data['quantity_value'])
                self.status_callback(f"Updating quantity_value: {product_data['quantity_value']}")
            
            if 'quantity_unit' in product_data:
                update_fields.append("quantity_unit = %s")
                update_values.append(product_data['quantity_unit'])
                self.status_callback(f"Updating quantity_unit: {product_data['quantity_unit']}")
            
            # Update country of origin if provided
            if 'country_of_origin' in product_data and product_data['country_of_origin']:
                update_fields.append("country_of_origin = %s")
                update_values.append(product_data['country_of_origin'])
                self.status_callback(f"Updating country_of_origin: {product_data['country_of_origin']}")
            
            # Execute product table update if there are fields to update
            if update_fields:
                update_fields.append("updated_at = CURRENT_TIMESTAMP")
                update_query = f"""
                    UPDATE products 
                    SET {', '.join(update_fields)}
                    WHERE product_id = %s
                """
                update_values.append(product_id)
                
                self._execute_query(update_query, tuple(update_values))
                self.status_callback(f"Updated {len(update_fields)} product fields")
            
            # Force update nutrition data if provided
            if 'nutrition_data' in product_data and product_data['nutrition_data']:
                self.force_update_nutrition_data(product_id, product_data['nutrition_data'], force_overwrite)
            
            # Force update price if provided (skip for new products to prevent dual entries)
            if 'price' in product_data and not is_new_product:
                price_decimal = self._parse_price(product_data['price'])
                if price_decimal is not None:
                    # Use explicit is_available from product_data if provided, otherwise derive from price
                    is_available = product_data.get('is_available', price_decimal > 0)
                    # Override availability for hidden products
                    if existing_product.get('is_hidden'):
                        is_available = False
                        self.status_callback(f"Product {sku} is hidden — forcing is_available=False")
                    
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
                    
                    # Add deduplication check - only record if significantly different from latest price
                    if self._should_record_price_update(product_id, price_decimal, is_available):
                        self._add_price_history_record(
                            product_id, price_decimal, is_available, 'force_update',
                            price_per_unit=price_per_unit, price_per_unit_type=price_per_unit_type,
                            discount_price=discount_price, discount_price_per_unit=discount_price_per_unit
                        )
                        self.status_callback(f"Updated price: €{price_decimal} (available: {is_available})")
                    else:
                        self.status_callback(f"Skipped duplicate price record: €{price_decimal} (already recorded today)")
                else:
                    self.status_callback(f"Invalid price format, skipping price update")
            elif 'price' in product_data and is_new_product:
                self.status_callback(f"Skipped price history for new product {sku} (prevents dual entries)")
            
            # Process ingredients if provided
            if 'ingredients' in product_data and product_data['ingredients']:
                self.force_update_ingredients(sku, product_data['ingredients'])
            
            # Process photos if provided
            if 'photos' in product_data and product_data['photos']:
                photos_saved = self.add_product_photos(product_id, product_data['photos'])
                if photos_saved:
                    self.status_callback(f"✓ Successfully saved {len(product_data['photos'])} photo(s) for product {sku}")
                else:
                    self.status_callback(f"⚠ Failed to save photos for product {sku} - check logs above for specific error")

            # Link master data last so failures in the earlier enhanced update
            # cannot leave a brand/producer association from an unsuccessful run.
            if 'brand' in product_data or 'producer' in product_data:
                upsert_brand_producer(
                    self.conn,
                    product_id,
                    brand_name=product_data.get('brand'),
                    producer_name=product_data.get('producer'),
                    status_callback=self.status_callback,
                )
            
            self.conn.commit()
            self.status_callback(f"Successfully force-updated product {sku}")
            return True
            
        except Exception as e:
            self.conn.rollback()
            self.status_callback(f"Error force-updating product {sku}: {str(e)}")
            return False

    def save_brand_producer_data(
        self,
        product_id: int,
        brand_name: Optional[str] = None,
        producer_name: Optional[str] = None,
    ) -> bool:
        """Attach scraped master data without clearing omitted values."""
        try:
            upsert_brand_producer(
                self.conn,
                product_id,
                brand_name=brand_name,
                producer_name=producer_name,
                status_callback=self.status_callback,
            )
            self.conn.commit()
            return True
        except Exception as e:
            self.conn.rollback()
            self.status_callback(f"Brand/producer save failed: {e}")
            return False
    
    def force_update_nutrition_data(self, product_id: int, nutrition_data: Dict, force_overwrite: bool = True) -> bool:
        """
        Force update nutrition data, overwriting NULL or corrupted values
        
        Args:
            product_id: Product ID
            nutrition_data: Nutrition data dictionary
            force_overwrite: Whether to overwrite existing non-NULL values
            
        Returns:
            True if successful
        """
        try:
            self.status_callback(f"Force updating nutrition data for product ID: {product_id}")
            
            # Check if nutrition record exists
            existing_nutrition = self._execute_query(
                "SELECT * FROM nutritionfacts WHERE product_id = %s",
                (product_id,),
                fetch=True
            )
            
            if existing_nutrition:
                existing_record = existing_nutrition[0]
                
                if existing_record.get('nutrition_manual_edit') and not force_overwrite:
                    self.status_callback("Skipping nutrition update - product marked as manually edited")
                    return True
                
                # Update existing record - build dynamic UPDATE query
                update_fields = []
                update_values = []
                
                nutrition_fields = [
                    'ingredients_text', 'energy_kcal', 'energy_kj', 'fat_total', 'fat_saturated',
                    'carbs_total', 'carbs_sugars', 'protein', 'salt', 'fiber'
                ]
                
                for field in nutrition_fields:
                    if field in nutrition_data:
                        current_value = existing_record.get(field)
                        new_value = nutrition_data[field]
                        
                        # Update if: force_overwrite=True, current value is NULL, or new value is not zero/empty
                        should_update = (
                            force_overwrite or 
                            current_value is None or 
                            (new_value and new_value != 0)
                        )
                        
                        if should_update:
                            update_fields.append(f"{field} = %s")
                            update_values.append(new_value)
                            self.status_callback(f"Updating {field}: {current_value} -> {new_value}")
                
                if update_fields:
                    update_fields.append("data_source_date = CURRENT_TIMESTAMP")
                    update_query = f"""
                        UPDATE nutritionfacts 
                        SET {', '.join(update_fields)}
                        WHERE product_id = %s
                    """
                    update_values.append(product_id)
                    
                    self._execute_query(update_query, tuple(update_values))
                    self.status_callback(f"✓ Successfully updated {len(update_fields)-1} nutrition fields in nutritionfacts table")
                    
                    # Show detailed save results
                    self.status_callback("=== NUTRITIONFACTS TABLE SAVE RESULTS ===")
                    for field in update_fields[:-1]:  # Exclude timestamp field
                        field_name = field.split(' = ')[0]
                        self.status_callback(f"  ✓ {field_name} saved to database")
                    self.status_callback("=" * 45)
                
                # Force recalculate nutri-score if nutrition data was updated
                if update_fields and len(update_fields) > 1:  # More than just timestamp
                    self.force_recalculate_nutriscore(product_id)
                    
            else:
                # Create new nutrition record
                self.status_callback("Creating new nutrition record")
                self.add_nutrition_data(product_id, nutrition_data)
            
            # Commit the transaction
            self.conn.commit()
            self.status_callback("✓ Committed nutrition update to database")
            
            return True
            
        except Exception as e:
            self.status_callback(f"Error force-updating nutrition data: {str(e)}")
            return False
    
    def force_recalculate_nutriscore(self, product_id: int) -> bool:
        """Force recalculate nutri-score for a product using 2024 algorithm with category detection"""
        try:
            # Get nutrition data WITH ingredients_text and energy_kj
            nutrition_query = """
                SELECT energy_kcal, energy_kj, fat_total, fat_saturated, carbs_total, carbs_sugars, 
                       protein, salt, fiber, ingredients_text
                FROM nutritionfacts 
                WHERE product_id = %s
            """
            nutrition_result = self._execute_query(nutrition_query, (product_id,), fetch=True)
            
            # Get product name and category ID for saved Nutri-Score type lookup.
            product_query = """
                SELECT p.name, p.category_id
                FROM products p
                WHERE p.product_id = %s
            """
            product_result = self._execute_query(product_query, (product_id,), fetch=True)
            product_name = product_result[0].get('name') if product_result else None
            category_id = product_result[0].get('category_id') if product_result else None
            
            if not nutrition_result:
                self.status_callback("No nutrition data found for nutri-score calculation")
                return False
            
            nutrition = nutrition_result[0]
            
            # Check if we have required fields for nutri-score calculation
            self.status_callback("=== NUTRI-SCORE CALCULATION ANALYSIS ===")
            required_fields = ['energy_kcal', 'fat_total', 'fat_saturated', 'carbs_total', 'carbs_sugars', 'protein', 'salt']
            
            # Show detailed field analysis
            missing_fields = []
            present_fields = []
            for field in required_fields:
                value = nutrition.get(field)
                if value is not None:
                    present_fields.append(f"{field}: {value}")
                else:
                    missing_fields.append(field)
            
            self.status_callback(f"Present fields ({len(present_fields)}):")
            for field in present_fields:
                self.status_callback(f"  ✓ {field}")
            
            if missing_fields:
                self.status_callback(f"Missing fields ({len(missing_fields)}):")
                for field in missing_fields:
                    self.status_callback(f"  ✗ {field}")
            
            has_required_data = len(missing_fields) == 0
            
            if not has_required_data:
                self.status_callback("✗ NUTRI-SCORE CALCULATION FAILED: Insufficient nutrition data")
                self.status_callback("=" * 50)
                return False
            
            # Check if ALL basic nutrition values are zero (needs enrichment case)
            # These products have no real nutrition data - likely from Rimi pages without nutrition table
            basic_nutrition_fields = ['energy_kcal', 'fat_total', 'carbs_total', 'protein', 'salt']
            all_zeros = all(
                (nutrition.get(field) or 0) == 0 
                for field in basic_nutrition_fields
            )
            
            if all_zeros:
                self.status_callback("⚠ ALL BASIC NUTRITION VALUES ARE ZERO")
                self.status_callback("  This product needs nutrition data enrichment")
                
                # Set needs_enrichment = TRUE on products table
                self._execute_query(
                    "UPDATE products SET needs_enrichment = TRUE WHERE product_id = %s",
                    (product_id,)
                )
                self.status_callback("  ✓ Set needs_enrichment = TRUE on products table")
                
                # Clear nutri-score (should not have a score if no real data)
                self._execute_query(
                    "UPDATE nutritionfacts SET nutri_score_grade = NULL, nutri_score_points = NULL WHERE product_id = %s",
                    (product_id,)
                )
                self.status_callback("  ✓ Cleared nutri_score_grade and nutri_score_points (set to NULL)")
                self.status_callback("=" * 50)
                return False
            
            # Calculate nutri-score using the 2024 calculator with category and sweetener detection
            self.status_callback("✓ All required fields present with non-zero values - proceeding with calculation")
            try:
                from nutriscore_calculator import NutriscoreCalculator
                
                # Convert kcal to kj if needed (1 kcal = 4.184 kj)
                energy_kj = nutrition.get('energy_kj', 0) or (nutrition.get('energy_kcal', 0) * 4.184 if nutrition.get('energy_kcal') else 0)
                ingredients_text = nutrition.get('ingredients_text', '') or ''
                
                # Show input values for calculation
                self.status_callback("Input values for nutri-score calculation (2024 algorithm):")
                self.status_callback(f"  - energy_kj: {energy_kj}")
                self.status_callback(f"  - sugars: {nutrition.get('carbs_sugars', 0) or 0}")
                self.status_callback(f"  - saturated_fat: {nutrition.get('fat_saturated', 0) or 0}")
                self.status_callback(f"  - salt: {nutrition.get('salt', 0) or 0}")
                self.status_callback(f"  - protein: {nutrition.get('protein', 0) or 0}")
                self.status_callback(f"  - fiber: {nutrition.get('fiber', 0) or 0}")
                self.status_callback(f"  - total_fat: {nutrition.get('fat_total', 0) or 0}")
                self.status_callback(f"  - category_id: {category_id}")
                self.status_callback(f"  - product_name: {product_name}")
                self.status_callback(f"  - ingredients_text: {ingredients_text[:100]}..." if len(ingredients_text) > 100 else f"  - ingredients_text: {ingredients_text}")
                
                calculator = NutriscoreCalculator(self.conn)
                nutri_result = calculator.calculate_single_product(
                    energy_kj=energy_kj,
                    sugars=nutrition.get('carbs_sugars', 0) or 0,
                    saturated_fat=nutrition.get('fat_saturated', 0) or 0,
                    salt=nutrition.get('salt', 0) or 0,
                    protein=nutrition.get('protein', 0) or 0,
                    fiber=nutrition.get('fiber', 0) or 0,
                    total_fat=nutrition.get('fat_total', 0) or 0,
                    product_name=product_name,
                    ingredients_text=ingredients_text,
                    category_id=category_id,
                )
                
                # Handle result from NutriscoreCalculator
                if nutri_result and nutri_result.get('success'):
                    grade = nutri_result['grade']
                    points = nutri_result['score']
                    
                    # Log classification details
                    classification = nutri_result.get('classification', {})
                    self.status_callback(f"  - Detected category: {classification.get('nutriscore_category', 'general')}")
                    self.status_callback(f"  - Is beverage: {classification.get('is_beverage', False)}")
                    self.status_callback(f"  - Has sweeteners: {classification.get('has_sweeteners', False)}")
                    self.status_callback(f"  - Protein status: {nutri_result.get('protein_status', 'included')}")
                    
                    # Log component breakdown
                    components = nutri_result.get('components', {})
                    if components:
                        self.status_callback(f"  - N points breakdown: energy={components.get('energy_points',0)}, sugar={components.get('sugar_points',0)}, satfat={components.get('satfat_points',0)}, salt={components.get('salt_points',0)}, sweetener={components.get('sweetener_points',0)}")
                        self.status_callback(f"  - P points breakdown: protein={components.get('protein_points',0)}, fiber={components.get('fiber_points',0)}, fvl={components.get('fvl_points',0)}")
                    
                    self.status_callback(f"Nutri-score calculated: {grade} ({points} points)")
                    
                    # Update nutri-score in database
                    update_query = """
                        UPDATE nutritionfacts 
                        SET nutri_score_grade = %s, nutri_score_points = %s, data_source_date = CURRENT_TIMESTAMP
                        WHERE product_id = %s
                    """
                    self._execute_query(update_query, (grade, points, product_id))
                    self.status_callback(f"✓ NUTRI-SCORE CALCULATION SUCCESS: {grade} ({points} points)")
                    self.status_callback("=" * 50)
                    return True
                else:
                    error_msg = nutri_result.get('error', 'Unknown error') if nutri_result else 'No result'
                    self.status_callback(f"✗ NUTRI-SCORE CALCULATION FAILED: {error_msg}")
                    self.status_callback("=" * 50)
                
            except ImportError as e:
                self.status_callback(f"✗ NUTRI-SCORE CALCULATION FAILED: Calculator module not available")
                self.status_callback(f"Import error: {str(e)}")
                self.status_callback("=" * 50)
            except Exception as e:
                self.status_callback(f"✗ NUTRI-SCORE CALCULATION FAILED: {str(e)}")
                self.status_callback(f"Error type: {type(e).__name__}")
                self.status_callback("=" * 50)
            
            return False
            
        except Exception as e:
            self.status_callback(f"Error recalculating nutri-score: {str(e)}")
            return False
    
    def force_update_ingredients(self, sku: str, ingredients_text: str) -> bool:
        """Force update ingredients, removing old mappings and creating new ones"""
        try:
            self.status_callback(f"Force updating ingredients for SKU: {sku}")
            
            # Get product ID
            product = self.get_product_by_sku(sku)
            if not product:
                return False
            
            product_id = product['product_id']
            
            # Remove existing ingredient mappings
            delete_query = "DELETE FROM ingredient_product_mapping WHERE product_sku = %s"
            self._execute_query(delete_query, (sku,))
            self.status_callback("Removed existing ingredient mappings")
            
            # Process ingredients using the ingredient processor
            if not ingredients_text or ingredients_text.strip() == '':
                self.status_callback(f"No ingredients found for SKU {sku} - this is normal for basic single-ingredient products")
                return True  # Return success - not having ingredients is not an error
            
            try:
                from ingredient_processor import IngredientProcessor
                processor = IngredientProcessor(self.status_callback)
                result = processor.process_product_ingredients(sku, ingredients_text)
                processor.close()
                
                # Check if any ingredients were processed (the correct key is 'processed', not 'success')
                if result.get('processed', 0) > 0:
                    self.status_callback(f"Successfully processed {result.get('processed', 0)} ingredients")
                else:
                    self.status_callback(f"No ingredients could be processed from text: '{ingredients_text[:50]}...' - this may be normal for basic products")

                # Assign NOVA score now that all ingredient suspicion levels are set
                try:
                    from nova_calculator import assign_nova_score
                    nova_result = assign_nova_score(self.conn, product_id, sku)
                    if not nova_result['skipped']:
                        self.status_callback(
                            f"NOVA assigned: {nova_result['nova_score']} ({nova_result['nova_source']})"
                        )
                except Exception as nova_exc:
                    self.status_callback(f"NOVA assignment skipped: {nova_exc}")

                return True
                    
            except ImportError:
                self.status_callback("Ingredient processor not available")
                return False
            
        except Exception as e:
            self.status_callback(f"Error force-updating ingredients: {str(e)}")
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
            
            # Ensure transaction is committed
            try:
                self.conn.commit()
                self.status_callback(f"Successfully committed {photos_saved} photo(s) to database for product ID {product_id}")
                return True
            except Exception as e:
                self.status_callback(f"Failed to save in database: Error committing photo transaction - {str(e)}")
                try:
                    self.conn.rollback()
                    self.status_callback("Photo transaction rolled back")
                except:
                    pass
                return False
            
        except Exception as e:
            self.status_callback(f"Failed to save in database: Unexpected error in add_product_photos - {str(e)}")
            return False

    def get_product_by_sku(self, sku: str) -> Optional[Dict]:
        """Get existing product by SKU"""
        query = "SELECT * FROM products WHERE sku = %s"
        result = self._execute_query(query, (sku,), fetch=True)
        return dict(result[0]) if result else None
    
    def _parse_price(self, price_str: str) -> Optional[Decimal]:
        """Parse price string to Decimal"""
        if not price_str or price_str == 'N/A':
            return None
        
        try:
            # Remove currency symbols and spaces
            clean_price = re.sub(r'[€$\s]', '', str(price_str))
            # Replace comma with dot
            clean_price = clean_price.replace(',', '.')
            # Extract number
            price_match = re.search(r'(\d+\.?\d*)', clean_price)
            if price_match:
                return Decimal(price_match.group(1))
        except:
            pass
        
        return None
    
    def _should_record_price_update(self, product_id: int, new_price: Decimal, new_availability: bool) -> bool:
        """Check if we should record a price update (prevents duplicate entries)"""
        try:
            # Check for recent price history (within last 6 hours)
            recent_price_query = """
                SELECT price, is_available, data_source, recorded_at 
                FROM product_price_history 
                WHERE product_id = %s 
                  AND recorded_at >= NOW() - INTERVAL '6 hours'
                ORDER BY recorded_at DESC 
                LIMIT 1
            """
            result = self._execute_query(recent_price_query, (product_id,), fetch=True)
            
            if result:
                last_record = result[0]
                last_price = last_record['price']
                last_availability = last_record['is_available']
                
                # Skip if price and availability are identical
                if (abs(last_price - new_price) < 0.01 and 
                    last_availability == new_availability):
                    return False
                    
            return True  # Record if no recent entry or price/availability changed
        except Exception as e:
            self.status_callback(f"Error checking price history: {str(e)}")
            return True  # Default to recording if check fails
    
    def _add_price_history_record(self, product_id: int, price: Decimal, is_available: bool, data_source: str,
                                    price_per_unit: Optional[Decimal] = None, price_per_unit_type: Optional[str] = None,
                                    discount_price: Optional[Decimal] = None, discount_price_per_unit: Optional[Decimal] = None):
        """Add price history record with optional discount and price-per-unit data"""
        try:
            history_query = """
                INSERT INTO product_price_history (
                    product_id, price, is_available, data_source, recorded_at,
                    price_per_unit, price_per_unit_type, discount_price, discount_price_per_unit
                )
                VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP, %s, %s, %s, %s)
            """
            self._execute_query(history_query, (
                product_id, price, is_available, data_source,
                price_per_unit, price_per_unit_type, discount_price, discount_price_per_unit
            ))
        except Exception as e:
            self.status_callback(f"Error adding price history: {str(e)}")
    
    def add_nutrition_data(self, product_id: int, nutrition_data: Dict) -> bool:
        """Add new nutrition data record"""
        try:
            # Determine is_fiber_correct based on whether fiber was scraped
            scraped_fiber = nutrition_data.get('fiber')
            has_scraped_fiber = scraped_fiber is not None and float(scraped_fiber) > 0
            is_fiber_correct = has_scraped_fiber
            
            nutrition_query = """
                INSERT INTO nutritionfacts (
                    product_id, ingredients_text, energy_kcal, energy_kj, fat_total, fat_saturated,
                    carbs_total, carbs_sugars, protein, salt, fiber, data_source_date, is_fiber_correct
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP, %s)
                RETURNING nutrition_id
            """
            
            result = self._execute_query(nutrition_query, (
                product_id,
                nutrition_data.get('ingredients_text', ''),
                nutrition_data.get('energy_kcal', 0),
                nutrition_data.get('energy_kj', 0),
                nutrition_data.get('fat_total', 0),
                nutrition_data.get('fat_saturated', 0),
                nutrition_data.get('carbs_total', 0),
                nutrition_data.get('carbs_sugars', 0),
                nutrition_data.get('protein', 0),
                nutrition_data.get('salt', 0),
                nutrition_data.get('fiber', 0),
                is_fiber_correct
            ), fetch=True)
            
            if result:
                nutrition_id = result[0]['nutrition_id']
                self.status_callback(f"Added nutrition data with ID: {nutrition_id}")
                
                # Calculate nutri-score
                self.force_recalculate_nutriscore(product_id)
                
                # Commit the transaction
                self.conn.commit()
                self.status_callback("✓ Committed nutrition data to database")
                
                return True
            
            return False
            
        except Exception as e:
            self.status_callback(f"Error adding nutrition data: {str(e)}")
            return False
    
    def identify_corrupted_products(self) -> List[Dict]:
        """Identify products with corrupted or incomplete data"""
        try:
            self.status_callback("Identifying products with corrupted data...")
            
            corrupted_query = """
                SELECT p.product_id, p.sku, p.name, p.rimi_url, p.category_id,
                       nf.carbs_total, nf.carbs_sugars, nf.protein, nf.salt,
                       nf.nutri_score_grade, nf.nutri_score_points
                FROM products p
                LEFT JOIN nutritionfacts nf ON p.product_id = nf.product_id
                WHERE p.rimi_url IS NULL 
                   OR p.rimi_url = '' 
                   OR p.category_id = 1  -- Default wrong category
                   OR (nf.nutrition_id IS NOT NULL AND (
                       nf.carbs_total IS NULL OR 
                       nf.carbs_sugars IS NULL OR 
                       nf.protein IS NULL OR 
                       nf.salt IS NULL OR
                       nf.nutri_score_grade IS NULL
                   ))
                ORDER BY p.updated_at DESC
                LIMIT 50
            """
            
            result = self._execute_query(corrupted_query, fetch=True)
            
            if result:
                self.status_callback(f"Found {len(result)} products with corrupted data")
                return [dict(row) for row in result]
            else:
                self.status_callback("No corrupted products found")
                return []
                
        except Exception as e:
            self.status_callback(f"Error identifying corrupted products: {str(e)}")
            return []
    
    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()
            self.status_callback("Database connection closed")