"""
Enhanced Update Coordinator - Integrates robust web client and enhanced database updater
Fixes corrupted data by force-updating all fields and handling website unavailability
"""

from typing import Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime
import time

@dataclass
class ProcessingResult:
    """Result of single product processing"""
    success: bool
    sku: str
    operation: str  # 'create', 'update', 'force_update'
    changes: Dict
    errors: List[str]
    product_data: Dict

class EnhancedUpdateCoordinator:
    """Enhanced coordinator with retry logic and forced data updates"""
    
    def __init__(self, status_callback=None):
        self.status_callback = status_callback or (lambda msg: print(msg))
        self.web_client = None
        self.db_updater = None
        self._initialize_components()
    
    def _initialize_components(self):
        """Initialize web client and database updater with retry logic for threading"""
        max_retries = 3
        retry_count = 0
        
        while retry_count < max_retries:
            try:
                self.status_callback(f"🔧 COORDINATOR: Initializing components (attempt {retry_count + 1}/{max_retries})")
                
                self.status_callback(f"🔧 COORDINATOR: Importing RobustWebClient...")
                from robust_web_client import RobustWebClient
                
                self.status_callback(f"🔧 COORDINATOR: Importing EnhancedDatabaseUpdater...")
                from enhanced_database_updater import EnhancedDatabaseUpdater
                
                self.status_callback(f"🔧 COORDINATOR: Creating RobustWebClient instance...")
                self.web_client = RobustWebClient(self.status_callback)
                self.status_callback(f"🔧 COORDINATOR: Web client created: {type(self.web_client)}")
                
                self.status_callback(f"🔧 COORDINATOR: Creating EnhancedDatabaseUpdater instance...")
                self.db_updater = EnhancedDatabaseUpdater(self.status_callback)
                self.status_callback(f"🔧 COORDINATOR: DB updater created: {type(self.db_updater)}")
                
                # Verify components are properly initialized
                if self.web_client is None or self.db_updater is None:
                    raise Exception(f"Components initialized but are None: web_client={self.web_client}, db_updater={self.db_updater}")
                
                self.status_callback("✅ COORDINATOR: Enhanced coordinator initialized with robust components")
                return
                
            except Exception as e:
                retry_count += 1
                self.status_callback(f"Error initializing components (attempt {retry_count}): {str(e)}")
                
                if retry_count < max_retries:
                    import time
                    time.sleep(1)  # Brief delay before retry
                else:
                    self.status_callback("Failed to initialize components after all retries")
                    self.web_client = None
                    self.db_updater = None
    
    def process_single_product_with_auto_category(self, sku: str, force_update: bool = False, fallback_category_code: Optional[str] = None) -> ProcessingResult:
        """
        Process single product with automatic category extraction from product page
        
        Args:
            sku: Product SKU to process
            force_update: Whether to force update existing data
            fallback_category_code: Category code to use if extracted category doesn't exist in DB
            
        Returns:
            ProcessingResult with success status and details
        """
        self.status_callback(f"🔄 COORDINATOR: Processing product {sku} with automatic category extraction")
        import threading
        self.status_callback(f"🔄 COORDINATOR: Thread ID: {threading.current_thread().ident}")
        self.status_callback(f"🔄 COORDINATOR: Thread name: {threading.current_thread().name}")
        
        result = ProcessingResult(
            success=False,
            sku=sku,
            operation='',
            changes={},
            errors=[],
            product_data={}
        )
        
        try:
            # Step 1: Get product data to extract category
            self.status_callback("🔄 COORDINATOR: Step 1: Fetching product data for category extraction...")
            
            # Check if components are properly initialized
            self.status_callback(f"🔍 COORDINATOR: Checking component initialization...")
            self.status_callback(f"🔍 COORDINATOR: Web client: {type(self.web_client) if self.web_client else 'None'}")
            self.status_callback(f"🔍 COORDINATOR: DB updater: {type(self.db_updater) if self.db_updater else 'None'}")
            
            if not self.web_client:
                error_msg = "Web client not initialized - component initialization failed"
                result.errors.append(error_msg)
                self.status_callback(f"❌ COORDINATOR: {error_msg}")
                # Try to reinitialize once more
                self.status_callback("🔧 COORDINATOR: Attempting to reinitialize components...")
                self._initialize_components()
                if not self.web_client:
                    self.status_callback("❌ COORDINATOR: Reinitialization failed - cannot proceed")
                    return result
                else:
                    self.status_callback("✅ COORDINATOR: Reinitialization successful")
            
            if not self.db_updater:
                error_msg = "Database updater not initialized - component initialization failed"
                result.errors.append(error_msg)
                self.status_callback(f"❌ COORDINATOR: {error_msg}")
                return result
                
            self.status_callback(f"🔄 COORDINATOR: Calling web_client.get_product_data({sku})...")
            product_data = self.web_client.get_product_data(sku)
            self.status_callback(f"🔍 COORDINATOR: Product data result: {type(product_data)}, keys: {list(product_data.keys()) if product_data else 'None'}")
            
            if not product_data:
                error_msg = "Product not found on website"
                result.errors.append(error_msg)
                self.status_callback(f"❌ COORDINATOR: {error_msg}")
                return result
            
            # Step 2: Extract category from product page
            self.status_callback("🔄 COORDINATOR: Step 2: Extracting category from product page...")
            self.status_callback(f"🔄 COORDINATOR: Calling extract_nutrition_data...")
            nutrition_data = self.web_client.extract_nutrition_data(product_data['soup'], product_data['url'])
            self.status_callback(f"🔍 COORDINATOR: Nutrition data keys: {list(nutrition_data.keys()) if nutrition_data else 'None'}")
            
            extracted_category = nutrition_data.get('category_code', '')
            category_path = nutrition_data.get('category_path_full', '')
            
            self.status_callback(f"🔍 COORDINATOR: Extracted category: '{extracted_category}'")
            self.status_callback(f"🔍 COORDINATOR: Category path: '{category_path}'")
            
            if extracted_category:
                # Validate that extracted category exists in normalized_categories
                extracted_category_id = self._get_category_id(extracted_category)
                
                if extracted_category_id:
                    self.status_callback(f"✅ COORDINATOR: Successfully extracted category: {extracted_category} from path: {category_path}")
                    category_code = extracted_category
                elif fallback_category_code:
                    # Extracted category doesn't exist in DB, use fallback from job
                    self.status_callback(f"⚠️ COORDINATOR: Extracted category {extracted_category} not found in DB, using job fallback: {fallback_category_code}")
                    category_code = fallback_category_code
                else:
                    self.status_callback(f"⚠️ COORDINATOR: Extracted category {extracted_category} not found in DB, using default SH-1-1-1")
                    category_code = 'SH-1-1-1'
            else:
                if fallback_category_code:
                    self.status_callback(f"⚠️ COORDINATOR: No category found on product page, using job fallback: {fallback_category_code}")
                    category_code = fallback_category_code
                else:
                    self.status_callback("⚠️ COORDINATOR: No category found on product page, using default SH-1-1-1")
                    category_code = 'SH-1-1-1'  # Default fallback
            
            # Step 3: Process with validated category
            self.status_callback(f"🔄 COORDINATOR: Step 3: Processing with category {category_code}")
            self.status_callback(f"🔄 COORDINATOR: Calling process_single_product_enhanced...")
            
            enhanced_result = self.process_single_product_enhanced(sku, category_code, force_update)
            self.status_callback(f"🔍 COORDINATOR: Enhanced processing result: success={enhanced_result.success}, operation={enhanced_result.operation}")
            if enhanced_result.errors:
                self.status_callback(f"🔍 COORDINATOR: Enhanced processing errors: {enhanced_result.errors}")
            
            return enhanced_result
            
        except Exception as e:
            error_msg = f"Error in automatic category processing: {str(e)}"
            result.errors.append(error_msg)
            self.status_callback(error_msg)
            return result

    def process_single_product_enhanced(self, sku: str, category_code: str, force_update: bool = False) -> ProcessingResult:
        """
        Process a single product with enhanced retry logic and data corruption handling
        
        Args:
            sku: Product SKU
            category_code: Category code for the product
            force_update: Whether to force update even if product exists with complete data
            
        Returns:
            ProcessingResult with detailed operation results
        """
        start_time = time.time()
        
        result = ProcessingResult(
            success=False,
            sku=sku,
            operation='',
            changes={},
            errors=[],
            product_data={}
        )
        
        try:
            self.status_callback(f"=== Enhanced Processing: SKU {sku} ===")
            
            # Step 1: Check existing product and determine if force update needed
            existing_product = self.db_updater.get_product_by_sku(sku)
            needs_force_update = False
            
            if existing_product:
                # Only perform force update for existing products with detected corruption or explicit request
                needs_force_update = self._check_data_corruption(existing_product)
                if needs_force_update:
                    self.status_callback(f"Detected corrupted data for SKU {sku} - will force update")
                elif force_update:
                    self.status_callback(f"Force update explicitly requested for existing product {sku}")
                    needs_force_update = True
                else:
                    self.status_callback(f"Product {sku} exists with valid data - no update needed")
            else:
                # For new products, skip force update logic entirely (prevents dual data source entries)
                self.status_callback(f"Product {sku} is new - will create with regular processing (no force update)")
            
            # Step 2: Fetch product data with retry logic
            self.status_callback("Fetching product data with retry logic...")
            product_data = self.web_client.get_product_data(sku)
            
            if not product_data:
                result.errors.append("Product not found on website after retry attempts")
                self.status_callback("Product not accessible on website")
                return result
            
            # Step 3: Extract additional data
            self.status_callback("Extracting nutrition and additional data...")
            
            # Get nutrition data with detailed parsing output
            self.status_callback("=== NUTRITION DATA PARSING ===")
            nutrition_data = self.web_client.extract_nutrition_data(product_data['soup'], product_data['url'])
            
            # Show detailed nutrition parsing results
            if nutrition_data.get('has_nutrition'):
                self.status_callback(f"✓ Nutrition data found with {len([k for k, v in nutrition_data.items() if v is not None and k != 'has_nutrition'])} values:")
                for key, value in nutrition_data.items():
                    if key != 'has_nutrition' and value is not None:
                        self.status_callback(f"  - {key}: {value}")
            else:
                self.status_callback("○ No nutrition labels found on product page")
                self.status_callback("  (Normal for oils, single ingredients, etc.)")
            
            product_data['nutrition_data'] = nutrition_data
            self.status_callback("=" * 35)
            
            # Get category ID
            category_id = self._get_category_id(category_code)
            if not category_id:
                result.errors.append(f"Invalid category code: {category_code}")
                return result
            
            product_data['category_id'] = category_id
            
            # Parse quantity from name
            quantity_value, quantity_unit = self._parse_quantity(product_data['name'])
            if quantity_value or quantity_unit:
                product_data['quantity_value'] = quantity_value
                product_data['quantity_unit'] = quantity_unit
            
            # Step 4: Database operation
            is_new_product = existing_product is None
            
            if existing_product and (needs_force_update or force_update):
                # Force update existing corrupted product
                result.operation = 'force_update'
                self.status_callback("Performing force update of corrupted existing product...")
                
                # Prepare complete product data for force update (include all price fields)
                update_data = {
                    'rimi_url': product_data['url'],
                    'category_id': category_id,
                    'name': product_data['name'],
                    'price': product_data['price'],
                    'is_available': product_data.get('is_available', True),
                    'nutrition_data': nutrition_data,
                    'ingredients': nutrition_data.get('ingredients', ''),
                    'quantity_value': quantity_value,
                    'quantity_unit': quantity_unit,
                    'country_of_origin': nutrition_data.get('country_of_origin', 'Unknown'),
                    'brand': product_data.get('brand') or nutrition_data.get('brand'),
                    'producer': product_data.get('producer') or nutrition_data.get('producer'),
                    'price_per_unit': product_data.get('price_per_unit'),
                    'price_per_unit_type': product_data.get('price_per_unit_type'),
                    'discount_price': product_data.get('discount_price'),
                    'discount_price_per_unit': product_data.get('discount_price_per_unit')
                }
                
                # Pass information about whether this is a new product to prevent dual price history
                success = self.db_updater.force_update_product_data(
                    sku, update_data, force_overwrite=True, is_new_product=False
                )
                
                if success:
                    # Save photos if available - continue processing even if photos fail
                    photos_saved = False
                    photo_error = None
                    if product_data.get('photos'):
                        existing_product = self.db_updater.get_product_by_sku(sku)
                        if existing_product:
                            try:
                                photos_saved = self.db_updater.add_product_photos(
                                    existing_product['product_id'], product_data['photos']
                                )
                                if photos_saved:
                                    self.status_callback(f"Photos processing: Successfully saved photo for product {sku}")
                                else:
                                    self.status_callback(f"Photos processing: Failed to save photo for product {sku} - check logs above for specific error")
                            except Exception as e:
                                photo_error = str(e)
                                self.status_callback(f"Photos processing: Exception during photo save for product {sku} - {photo_error}")
                        else:
                            self.status_callback(f"Photos processing: Product {sku} not found in database for photo association")
                    else:
                        self.status_callback(f"Photos processing: No photos extracted for product {sku}")
                    
                    # Save ingredients if available - continue processing even if ingredients fail
                    ingredients_saved = False
                    ingredient_error = None
                    if nutrition_data.get('ingredients'):
                        try:
                            ingredients_saved = self.db_updater.force_update_ingredients(
                                sku, nutrition_data['ingredients']
                            )
                            if ingredients_saved:
                                self.status_callback(f"Ingredients processing: Successfully saved for product {sku}")
                            else:
                                self.status_callback(f"Ingredients processing: Failed to save for product {sku}")
                        except Exception as e:
                            ingredient_error = str(e)
                            self.status_callback(f"Ingredients processing: Exception during save for product {sku} - {ingredient_error}")
                    else:
                        self.status_callback(f"Ingredients processing: No ingredients extracted for product {sku}")
                    
                    result.success = True
                    result.changes = {
                        'forced_update': True,
                        'rimi_url_updated': bool(product_data['url']),
                        'category_updated': True,
                        'nutrition_updated': nutrition_data.get('has_nutrition', False),
                        'ingredients_updated': bool(nutrition_data.get('ingredients')),
                        'price_updated': True,
                        'photos_saved': photos_saved,
                        'ingredients_saved': ingredients_saved,
                        'photo_error': photo_error,
                        'ingredient_error': ingredient_error
                    }
                    
                    # Overall success message
                    success_parts = []
                    if photos_saved:
                        success_parts.append("photos saved")
                    if ingredients_saved:
                        success_parts.append("ingredients saved")
                    
                    additional_info = ""
                    if success_parts:
                        additional_info = f" with {' and '.join(success_parts)}"
                    
                    self.status_callback(f"Force update completed successfully{additional_info}")
                else:
                    result.errors.append("Force update failed")
                    
            elif existing_product:
                # Regular update for existing product
                result.operation = 'update'
                self.status_callback("Performing regular update...")
                
                # Update price and availability
                price_decimal = self._parse_price(product_data['price'])
                # Use explicit is_available from product_data (extracted from page)
                is_available = product_data.get('is_available', True)
                
                success = self._update_existing_product(sku, product_data, is_available)
                
                if success:
                    result.success = True
                    result.changes = {
                        'price_updated': True,
                        'nutrition_updated': nutrition_data.get('has_nutrition', False),
                        'availability_updated': True
                    }
                else:
                    result.errors.append("Regular update failed")
                    
            else:
                # Create new product
                result.operation = 'create'
                self.status_callback("Creating new product...")
                
                success = self._create_new_product(sku, product_data, category_id)
                
                if success:
                    result.success = True
                    result.changes = {
                        'product_created': True,
                        'nutrition_added': nutrition_data.get('has_nutrition', False),
                        'ingredients_added': bool(nutrition_data.get('ingredients'))
                    }
                else:
                    result.errors.append("Product creation failed")
            
            # Store processed data for display
            result.product_data = {
                'name': product_data['name'],
                'price': product_data['price'],
                'url': product_data['url'],
                'brand': product_data.get('brand'),
                'producer': product_data.get('producer'),
                'category_id': category_id,
                'quantity_value': quantity_value,
                'quantity_unit': quantity_unit,
                'nutrition': nutrition_data
            }
            
            processing_time = time.time() - start_time
            self.status_callback(f"Processing completed in {processing_time:.2f}s")
            
            return result
            
        except Exception as e:
            result.errors.append(f"Processing error: {str(e)}")
            self.status_callback(f"Processing failed: {str(e)}")
            return result
    
    def _check_data_corruption(self, product: Dict) -> bool:
        """Check if product has corrupted or incomplete data"""
        corruption_indicators = [
            not product.get('rimi_url'),  # Missing URL
            product.get('category_id') == 1,  # Default wrong category
        ]
        
        # Check nutrition data corruption
        try:
            nutrition_query = """
                SELECT carbs_total, carbs_sugars, protein, salt, nutri_score_grade,
                       energy_kcal, fat_total
                FROM nutritionfacts WHERE product_id = %s
            """
            nutrition_result = self.db_updater._execute_query(
                nutrition_query, (product['product_id'],), fetch=True
            )
            
            if nutrition_result:
                nutrition = nutrition_result[0]
                
                # Check if this is a "needs enrichment" case (all basic nutrition = 0)
                # In this case, NULL nutri_score is EXPECTED, not corruption
                basic_nutrition_fields = ['energy_kcal', 'fat_total', 'carbs_total', 'protein', 'salt']
                all_nutrition_zero = all(
                    (nutrition.get(field) or 0) == 0 
                    for field in basic_nutrition_fields
                )
                
                # Also check if product is already flagged for enrichment
                needs_enrichment = product.get('needs_enrichment', False)
                
                if all_nutrition_zero or needs_enrichment:
                    # Product has no real nutrition data - don't check nutri_score
                    # Only check for NULL values in core nutrition fields themselves
                    null_nutrition = [
                        nutrition.get('carbs_total') is None,
                        nutrition.get('carbs_sugars') is None,
                        nutrition.get('protein') is None,
                        nutrition.get('salt') is None,
                        # nutri_score_grade=NULL is EXPECTED here, not corruption
                    ]
                else:
                    # Product has real nutrition data - nutri_score should exist
                    null_nutrition = [
                        nutrition.get('carbs_total') is None,
                        nutrition.get('carbs_sugars') is None,
                        nutrition.get('protein') is None,
                        nutrition.get('salt') is None,
                        nutrition.get('nutri_score_grade') is None
                    ]
                corruption_indicators.extend(null_nutrition)
                
        except Exception as e:
            self.status_callback(f"Error checking nutrition corruption: {str(e)}")
        
        is_corrupted = any(corruption_indicators)
        if is_corrupted:
            corruption_count = sum(corruption_indicators)
            self.status_callback(f"Found {corruption_count} corruption indicators for SKU {product.get('sku')}")
        
        return is_corrupted
    
    def _update_existing_product(self, sku: str, product_data: Dict, is_available: bool) -> bool:
        """Update existing product with new data"""
        try:
            # Get explicit is_available from product_data if provided
            is_available = product_data.get('is_available', is_available)
            
            # Update price and availability
            price_decimal = self._parse_price(product_data['price'])
            if price_decimal is not None:
                # Add price history record with new price fields
                existing_product = self.db_updater.get_product_by_sku(sku)
                if existing_product:
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
                    
                    self.db_updater._add_price_history_record(
                        existing_product['product_id'], price_decimal, is_available, 'enhanced_update',
                        price_per_unit=price_per_unit, price_per_unit_type=price_per_unit_type,
                        discount_price=discount_price, discount_price_per_unit=discount_price_per_unit
                    )
            
            # Update country of origin if available
            nutrition_data = product_data.get('nutrition_data', {})
            if nutrition_data.get('country_of_origin'):
                update_data = {
                    'country_of_origin': nutrition_data['country_of_origin']
                }
                if 'brand' in product_data:
                    update_data['brand'] = product_data.get('brand')
                if 'producer' in product_data:
                    update_data['producer'] = product_data.get('producer')
                self.db_updater.force_update_product_data(sku, update_data, force_overwrite=False, is_new_product=True)
            elif 'brand' in product_data or 'producer' in product_data:
                self.db_updater.force_update_product_data(
                    sku,
                    {
                        'brand': product_data.get('brand'),
                        'producer': product_data.get('producer'),
                    },
                    force_overwrite=False,
                    is_new_product=True,
                )
            
            # Update nutrition data if available
            if nutrition_data.get('has_nutrition'):
                existing_product = self.db_updater.get_product_by_sku(sku)
                if existing_product:
                    self.db_updater.force_update_nutrition_data(
                        existing_product['product_id'], nutrition_data, force_overwrite=False
                    )
            
            # Update ingredients if available
            if nutrition_data.get('ingredients'):
                self.db_updater.force_update_ingredients(sku, nutrition_data['ingredients'])
            
            # Update photos if available
            if product_data.get('photos'):
                existing_product = self.db_updater.get_product_by_sku(sku)
                if existing_product:
                    self.db_updater.add_product_photos(
                        existing_product['product_id'], product_data['photos']
                    )
            
            return True
            
        except Exception as e:
            self.status_callback(f"Error updating existing product: {str(e)}")
            return False
    
    def _create_new_product(self, sku: str, product_data: Dict, category_id: int) -> bool:
        """Create new product with complete data"""
        try:
            # Use enhanced updater's force update method for new products too
            # This ensures all data is properly set from the start
            nutrition_data = product_data.get('nutrition_data', {})
            new_product_data = {
                'sku': sku,
                'name': product_data['name'],
                'rimi_url': product_data['url'],
                'category_id': category_id,
                'price': product_data['price'],
                'is_available': product_data.get('is_available', True),
                'quantity_value': product_data.get('quantity_value'),
                'quantity_unit': product_data.get('quantity_unit'),
                'country_of_origin': nutrition_data.get('country_of_origin', 'Unknown'),
                'brand': product_data.get('brand') or nutrition_data.get('brand'),
                'producer': product_data.get('producer') or nutrition_data.get('producer'),
                'nutrition_data': nutrition_data,
                'ingredients': nutrition_data.get('ingredients', ''),
                'photos': product_data.get('photos', []),
                'price_per_unit': product_data.get('price_per_unit'),
                'price_per_unit_type': product_data.get('price_per_unit_type'),
                'discount_price': product_data.get('discount_price'),
                'discount_price_per_unit': product_data.get('discount_price_per_unit')
            }
            
            # First create basic product record (include all price fields and availability)
            basic_data = {
                'sku': sku,
                'name': product_data['name'],
                'url': product_data['url'],
                'brand': product_data.get('brand'),
                'producer': product_data.get('producer'),
                'category_id': category_id,
                'price': product_data['price'],
                'is_available': product_data.get('is_available', True),
                'price_per_unit': product_data.get('price_per_unit'),
                'price_per_unit_type': product_data.get('price_per_unit_type'),
                'discount_price': product_data.get('discount_price'),
                'discount_price_per_unit': product_data.get('discount_price_per_unit')
            }
            
            from database_updater import DatabaseUpdater
            basic_updater = DatabaseUpdater(self.status_callback)
            try:
                product_id = basic_updater.add_new_product(basic_data)
                basic_updater.close()
                
                if product_id:
                    # Now use enhanced updater to complete all data for newly created product
                    return self.db_updater.force_update_product_data(sku, new_product_data, force_overwrite=True, is_new_product=True)
                    
            except Exception as e:
                basic_updater.close()
                raise e
            
            return False
            
        except Exception as e:
            self.status_callback(f"Error creating new product: {str(e)}")
            return False
    
    def _get_category_id(self, category_code: str) -> Optional[int]:
        """Get category ID from category code
        
        Args:
            category_code: The Rimi category code (e.g., 'SH-2-2-10')
            
        Returns:
            Category ID if found, None if category doesn't exist in normalized_categories
        """
        try:
            from database_integration import ExternalDatabaseManager
            ext_db = ExternalDatabaseManager()
            categories = ext_db.get_all_categories()
            
            for category in categories:
                if category.rimi_category_code == category_code:
                    return category.category_id
            
            # Category not found - return None so caller can handle fallback
            self.status_callback(f"Category code {category_code} not found in normalized_categories")
            return None
            
        except Exception as e:
            self.status_callback(f"Error getting category ID: {str(e)}")
            return None
    
    def _parse_quantity(self, product_name: str) -> tuple:
        """Parse quantity from product name"""
        import re
        from decimal import Decimal

        if not product_name:
            return None, None

        name_lower = product_name.lower()

        # Check for multiplier pattern first: e.g. "25x2g", "6x0,33l", "20x1,5g"
        # Matches: multiplier x unit_qty unit  -> total = multiplier * unit_qty
        multiplier_pattern = r'(\d+)\s*[xX×]\s*(\d+(?:[.,]\d+)?)\s*(g|kg|ml|l)\b'
        m = re.search(multiplier_pattern, name_lower)
        if m:
            try:
                multiplier = Decimal(m.group(1))
                unit_qty = Decimal(m.group(2).replace(',', '.'))
                unit = m.group(3).lower()
                return multiplier * unit_qty, unit
            except:
                pass

        # Standard patterns with various units
        standard_pattern = r'(\d+(?:[.,]\d+)?)\s*(l|kg|g|ml|gb|gab|tk|tükk|m)\b'
        match = re.search(standard_pattern, name_lower)
        if match:
            try:
                quantity_value = Decimal(match.group(1).replace(',', '.'))
                quantity_unit = match.group(2)
                unit_mapping = {
                    'gb': 'gab',
                    'tk': 'gab',
                    'tükk': 'gab'
                }
                quantity_unit = unit_mapping.get(quantity_unit, quantity_unit)
                return quantity_value, quantity_unit
            except:
                pass

        # Patterns for products sold by piece count only
        piece_pattern = r'(\d+)\s*(gab\.?|tk\.?|tükk)'
        match = re.search(piece_pattern, name_lower)
        if match:
            try:
                quantity_value = Decimal(match.group(1))
                quantity_unit = unit_mapping = {'gab.': 'gab', 'tk.': 'gab', 'tükk': 'gab'}.get(match.group(2), 'gab')
                return quantity_value, quantity_unit
            except:
                pass

        return None, None
    
    def _parse_price(self, price_str: str) -> Optional[float]:
        """Parse price string to float"""
        if not price_str or price_str == 'N/A':
            return None
        
        try:
            import re
            # Remove currency symbols and spaces
            clean_price = re.sub(r'[€$\s]', '', str(price_str))
            # Replace comma with dot
            clean_price = clean_price.replace(',', '.')
            # Extract number
            price_match = re.search(r'(\d+\.?\d*)', clean_price)
            if price_match:
                return float(price_match.group(1))
        except:
            pass
        
        return None
    
    def fix_corrupted_products(self, limit: int = 10) -> Dict:
        """Find and fix products with corrupted data"""
        try:
            self.status_callback("Identifying corrupted products...")
            
            corrupted_products = self.db_updater.identify_corrupted_products()
            
            if not corrupted_products:
                return {'success': True, 'message': 'No corrupted products found', 'fixed': 0}
            
            fixed_count = 0
            errors = []
            
            for product in corrupted_products[:limit]:
                try:
                    sku = product['sku']
                    self.status_callback(f"Fixing corrupted product: {sku}")
                    
                    # Attempt to reprocess with force update
                    result = self.process_single_product_enhanced(sku, 'SH-1-1-1', force_update=True)
                    
                    if result.success:
                        fixed_count += 1
                        self.status_callback(f"Successfully fixed product {sku}")
                    else:
                        errors.extend(result.errors)
                        
                except Exception as e:
                    error_msg = f"Error fixing product {product.get('sku', 'unknown')}: {str(e)}"
                    errors.append(error_msg)
                    self.status_callback(error_msg)
            
            return {
                'success': True,
                'found': len(corrupted_products),
                'fixed': fixed_count,
                'errors': errors,
                'message': f'Fixed {fixed_count} of {len(corrupted_products)} corrupted products'
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'message': f'Error fixing corrupted products: {str(e)}'
            }
    
    def close(self):
        """Close all connections"""
        if self.web_client:
            self.web_client.close()
        if self.db_updater:
            self.db_updater.close()
        self.status_callback("Enhanced coordinator closed")