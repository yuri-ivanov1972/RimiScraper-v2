#!/usr/bin/env python3
"""
Update Coordinator - Orchestrates database updates with scraper integration
Handles the complete update workflow including product comparison and processing
"""
import time
from typing import Dict, List, Set, Tuple, Any
from datetime import datetime
from database_updater import DatabaseUpdater
from ingredient_processor import IngredientProcessor
from product_matcher import ProductMatcher

class UpdateCoordinator:
    """Coordinates the complete database update process"""
    
    def __init__(self, status_callback=None):
        self.status_callback = status_callback or (lambda x: None)
        self.db_updater = DatabaseUpdater(self.status_callback)
        self.ingredient_processor = IngredientProcessor(self.status_callback)
        self.product_matcher = ProductMatcher(self.status_callback)
        
        # Track products without nutrition facts
        self.products_without_nutrition = []
    
    def perform_category_update(self, category_code: str) -> Dict:
        """
        Perform complete update for a category
        
        Args:
            category_code: Category to update (e.g., 'SH-12-1-1')
            
        Returns:
            Dictionary with update results and statistics
        """
        start_time = datetime.now()
        self.status_callback(f"Starting update for category {category_code}")
        
        update_results = {
            'category': category_code,
            'start_time': start_time,
            'new_products_added': 0,
            'prices_updated': 0,
            'products_marked_unavailable': 0,
            'nutrition_data_added': 0,
            'ingredients_processed': 0,
            'products_without_nutrition': [],
            'errors': [],
            'processing_time': None
        }
        
        try:
            # Step 1: Get product comparison results
            self.status_callback("Comparing website vs database products")
            comparison_result = self.product_matcher.compare_products(category_code)
            
            # Step 2: Process new products
            if comparison_result.new_products:
                self.status_callback(f"Processing {len(comparison_result.new_products)} new products")
                new_results = self._process_new_products(comparison_result.new_products, category_code)
                update_results.update(new_results)
            
            # Step 3: Update existing product prices
            if comparison_result.changed_products:
                self.status_callback(f"Updating {len(comparison_result.changed_products)} product prices")
                price_results = self._process_price_updates(comparison_result.changed_products)
                update_results['prices_updated'] = price_results['updated']
            
            # Step 4: Mark missing products as unavailable
            if comparison_result.missing_products:
                self.status_callback(f"Marking {len(comparison_result.missing_products)} products as unavailable")
                unavailable_results = self._process_unavailable_products(comparison_result.missing_products)
                update_results['products_marked_unavailable'] = unavailable_results['marked']
            
            # Step 5: Collect products without nutrition facts
            update_results['products_without_nutrition'] = self.products_without_nutrition
            
            update_results['processing_time'] = (datetime.now() - start_time).total_seconds()
            self.status_callback(f"Update completed for {category_code} in {update_results['processing_time']:.2f} seconds")
            
            return update_results
            
        except Exception as e:
            error_msg = f"Update failed for {category_code}: {str(e)}"
            self.status_callback(error_msg)
            update_results['errors'].append(error_msg)
            update_results['processing_time'] = (datetime.now() - start_time).total_seconds()
            return update_results
    
    def _process_new_products(self, new_products: List, category_code: str) -> Dict:
        """Process new products found on website"""
        results = {
            'new_products_added': 0,
            'nutrition_data_added': 0,
            'ingredients_processed': 0,
            'errors': []
        }
        
        for product_match in new_products:
            try:
                website_data = product_match.website_data
                
                # Prepare product data
                product_data = {
                    'sku': website_data.sku,
                    'name': website_data.name,
                    'url': website_data.url,
                    'price': website_data.price,
                    'category_id': self._get_category_id(category_code)
                }
                
                # Add product to database
                product_id = self.db_updater.add_new_product(product_data)
                results['new_products_added'] += 1
                
                # Try to get nutrition data (this would be from detailed scraping)
                nutrition_data = self._get_nutrition_data(website_data.url)
                self.db_updater.save_brand_producer_data(
                    product_id,
                    nutrition_data.get('brand'),
                    nutrition_data.get('producer'),
                )
                
                if nutrition_data and nutrition_data.get('has_nutrition'):
                    # Add nutrition data with nutri-score calculation
                    self.db_updater.add_nutrition_data(product_id, nutrition_data, category_code)
                    results['nutrition_data_added'] += 1
                    
                    # Process ingredients for new products only
                    if nutrition_data.get('ingredients'):
                        ingredient_results = self.ingredient_processor.process_product_ingredients(
                            website_data.sku, 
                            nutrition_data['ingredients']
                        )
                        results['ingredients_processed'] += ingredient_results['processed']
                
                else:
                    # Track products without nutrition facts
                    self.products_without_nutrition.append({
                        'sku': website_data.sku,
                        'name': website_data.name,
                        'category': category_code,
                        'url': website_data.url
                    })
                    self.status_callback(f"Product {website_data.sku} has no nutrition data - added to tracking list")
                
                # Add a small delay to be respectful to the server
                time.sleep(0.2)
                
            except Exception as e:
                error_msg = f"Error processing new product {website_data.sku}: {str(e)}"
                results['errors'].append(error_msg)
                self.status_callback(error_msg)
        
        return results
    
    def _process_price_updates(self, changed_products: List) -> Dict:
        """Process price updates for existing products"""
        results = {'updated': 0, 'errors': []}
        
        for product_match in changed_products:
            try:
                website_data = product_match.website_data
                
                # Update price (all changes are tracked without review)
                success = self.db_updater.update_product_price(
                    website_data.sku,
                    website_data.price,
                    True  # Product is available since it's on website
                )
                
                if success:
                    results['updated'] += 1
                    
            except Exception as e:
                error_msg = f"Error updating price for {website_data.sku}: {str(e)}"
                results['errors'].append(error_msg)
                self.status_callback(error_msg)
        
        return results
    
    def _process_unavailable_products(self, missing_products: List) -> Dict:
        """Mark products as unavailable"""
        results = {'marked': 0, 'errors': []}
        
        for product_match in missing_products:
            try:
                sku = product_match.sku
                
                success = self.db_updater.mark_product_unavailable(sku)
                if success:
                    results['marked'] += 1
                    
            except Exception as e:
                error_msg = f"Error marking {sku} unavailable: {str(e)}"
                results['errors'].append(error_msg)
                self.status_callback(error_msg)
        
        return results
    
    def _get_nutrition_data(self, product_url: str) -> Dict:
        """
        Get nutrition data for a product URL by scraping the product page
        """
        import requests
        import json
        import re
        from bs4 import BeautifulSoup
        from decimal import Decimal, InvalidOperation
        
        try:
            if not product_url:
                return {'has_nutrition': False, 'ingredients': '', 'energy_kcal': 0, 'energy_kj': 0, 
                       'fat_total': 0, 'fat_saturated': 0, 'carbs_total': 0, 'carbs_sugars': 0, 
                       'protein': 0, 'salt': 0, 'fiber': 0}
            
            self.status_callback(f"Fetching nutrition data from: {product_url}")
            
            # Create session with proper headers
            session = requests.Session()
            session.headers.update({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'lv,en-US;q=0.7,en;q=0.3',
                'Accept-Encoding': 'gzip, deflate',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1'
            })
            
            response = session.get(product_url)
            if response.status_code != 200:
                self.status_callback(f"Failed to fetch product page: {response.status_code}")
                return {'has_nutrition': False, 'ingredients': '', 'energy_kcal': 0, 'energy_kj': 0, 
                       'fat_total': 0, 'fat_saturated': 0, 'carbs_total': 0, 'carbs_sugars': 0, 
                       'protein': 0, 'salt': 0, 'fiber': 0}
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Initialize nutrition data
            nutrition_data = {
                'has_nutrition': False,
                'ingredients': '',
                'brand': None,
                'producer': None,
                'energy_kcal': 0,
                'energy_kj': 0,
                'fat_total': 0,
                'fat_saturated': 0,
                'carbs_total': 0,
                'carbs_sugars': 0,
                'protein': 0,
                'salt': 0,
                'fiber': 0
            }
            from brand_producer import extract_brand_producer
            nutrition_data.update(extract_brand_producer(soup))
            
            # Helper function to extract decimal values
            def extract_decimal(text: str) -> float:
                try:
                    cleaned = re.sub(r'[^0-9.-]', '', text.replace(',', '.'))
                    return float(cleaned) if cleaned else 0.0
                except (ValueError, TypeError):
                    return 0.0
            
            # Helper function to extract energy values (kJ and kcal)
            def extract_energy_values(text: str) -> tuple:
                try:
                    pattern = r'(\d+(?:[,.]\d+)?)\s*kJ\s*(?:/|\s)\s*(\d+(?:[,.]\d+)?)\s*kcal'
                    match = re.search(pattern, text, re.IGNORECASE)
                    if match:
                        kj = extract_decimal(match.group(1))
                        kcal = extract_decimal(match.group(2))
                        return kj, kcal
                    return 0.0, 0.0
                except Exception:
                    return 0.0, 0.0
            
            # Find product details script containing nutrition information
            script_tag = None
            for script in soup.find_all('script'):
                if script.string and 'Storefront.product_details_page' in script.string:
                    script_tag = script
                    break
            
            if script_tag:
                script_content = script_tag.string
                self.status_callback("Found product details script")
                
                # Extract the details tab HTML content
                try:
                    details_match = re.search(
                        r'identifier:\s*["\']details["\'],[^}]*html:\s*["\']([^"\']+)["\']',
                        script_content, re.DOTALL)
                    
                    if not details_match:
                        details_match = re.search(
                            r'html:\s*["\']([^"\']+)["\'].*?identifier:\s*["\']details["\']',
                            script_content, re.DOTALL)
                    
                    if details_match:
                        html_content = details_match.group(1)
                        
                        # Handle escaped characters
                        html_content = html_content.encode().decode('unicode-escape')
                        html_content = html_content.replace('\\/', '/')
                        html_content = html_content.replace('\\"', '"')
                        
                        details_soup = BeautifulSoup(html_content, 'html.parser')
                        
                        # Find ingredients
                        for section in details_soup.find_all('div', class_='product__list-wrapper'):
                            heading = section.find('p', class_='heading')
                            if heading and 'Sastāvdaļas' in heading.get_text(strip=True):
                                text_div = section.find('div', class_='text')
                                if text_div and text_div.p:
                                    nutrition_data['ingredients'] = text_div.p.get_text(strip=True)
                                    self.status_callback(f"Found ingredients: {nutrition_data['ingredients'][:50]}...")
                                break
                        
                        # Find nutrition table
                        tables = details_soup.find_all('table')
                        nutrition_table = None
                        for table in tables:
                            headers = table.find_all('th')
                            if any('Uzturvērtība' in header.get_text(strip=True) for header in headers):
                                nutrition_table = table
                                self.status_callback("Found nutrition table")
                                break
                        
                        if nutrition_table:
                            nutrition_data['has_nutrition'] = True
                            for row in nutrition_table.find_all('tr'):
                                cells = row.find_all(['td'])
                                if len(cells) >= 2:
                                    label = cells[0].get_text(strip=True).lower()
                                    value = cells[1].get_text(strip=True)
                                    
                                    if 'enerģētiskā vērtība' in label:
                                        kj, kcal = extract_energy_values(value)
                                        nutrition_data['energy_kj'] = kj
                                        nutrition_data['energy_kcal'] = kcal
                                    elif 'tauki' in label and 'piesātinātās' not in label:  # Match "tauki" but not "piesātinātās taukskābes"
                                        nutrition_data['fat_total'] = extract_decimal(value)
                                    elif 'piesātinātās taukskābes' in label:  # Handles both "piesātinātās taukskābes" and "tostarp piesātinātās taukskābes"
                                        nutrition_data['fat_saturated'] = extract_decimal(value)
                                    elif 'ogļhidrāti' in label and 'cukuri' not in label:  # Match "ogļhidrāti" but not "tostarp cukuri"
                                        nutrition_data['carbs_total'] = extract_decimal(value)
                                    elif 'cukuri' in label:  # Handles both "cukuri" and "tostarp cukuri"
                                        nutrition_data['carbs_sugars'] = extract_decimal(value)
                                    elif 'olbaltumvielas' in label:
                                        nutrition_data['protein'] = extract_decimal(value)
                                    elif 'sāls' in label:
                                        nutrition_data['salt'] = extract_decimal(value)
                                    elif 'šķiedrvielas' in label or 'fiber' in label.lower():
                                        nutrition_data['fiber'] = extract_decimal(value)
                            
                            if nutrition_data['has_nutrition']:
                                self.status_callback(f"Successfully extracted nutrition data:")
                                self.status_callback(f"  Energy: {nutrition_data['energy_kcal']} kcal ({nutrition_data['energy_kj']} kJ)")
                                self.status_callback(f"  Fat: {nutrition_data['fat_total']}g (saturated: {nutrition_data['fat_saturated']}g)")
                                self.status_callback(f"  Carbohydrates: {nutrition_data['carbs_total']}g (sugars: {nutrition_data['carbs_sugars']}g)")
                                self.status_callback(f"  Protein: {nutrition_data['protein']}g, Salt: {nutrition_data['salt']}g")
                        
                        # If we found ingredients but no nutrition table, still mark as partial nutrition data
                        if nutrition_data['ingredients'] and not nutrition_data['has_nutrition']:
                            nutrition_data['has_nutrition'] = True
                            self.status_callback("Found ingredients only (no nutrition table)")
                
                except Exception as e:
                    self.status_callback(f"Error processing product details: {str(e)}")
            
            if not nutrition_data['has_nutrition']:
                self.status_callback("No nutrition data found on product page")
            
            return nutrition_data
            
        except Exception as e:
            self.status_callback(f"Error fetching nutrition data: {str(e)}")
            return {'has_nutrition': False, 'ingredients': '', 'energy_kcal': 0, 'energy_kj': 0, 
                   'fat_total': 0, 'fat_saturated': 0, 'carbs_total': 0, 'carbs_sugars': 0, 
                   'protein': 0, 'salt': 0, 'fiber': 0}
    
    def _get_category_id(self, category_code: str) -> int:
        """Get category ID from category code using normalized_categories table"""
        try:
            # Import here to avoid circular imports
            from database_integration import ExternalDatabaseManager
            
            # Get all categories and find the matching one
            db = ExternalDatabaseManager()
            categories = db.get_all_categories()
            
            # Find exact match for category code
            for category in categories:
                if category.rimi_category_code == category_code:
                    self.status_callback(f"Found category {category_code}: ID={category.category_id}, Name={category.name_lv}")
                    return category.category_id
            
            # If not found, log warning and return default
            self.status_callback(f"Warning: Category {category_code} not found in normalized_categories, using default ID=1")
            return 1
            
        except Exception as e:
            self.status_callback(f"Error getting category ID for {category_code}: {str(e)}, using default ID=1")
            return 1
    
    def get_update_summary(self, update_results: Dict) -> str:
        """Generate human-readable summary of update results"""
        summary_lines = [
            f"Update Summary for {update_results['category']}:",
            f"Processing time: {update_results['processing_time']:.2f} seconds",
            "",
            f"✓ New products added: {update_results['new_products_added']}",
            f"✓ Prices updated: {update_results['prices_updated']}",
            f"✓ Products marked unavailable: {update_results['products_marked_unavailable']}",
            f"✓ Nutrition data added: {update_results['nutrition_data_added']}",
            f"✓ Ingredients processed: {update_results['ingredients_processed']}",
            ""
        ]
        
        if update_results['products_without_nutrition']:
            summary_lines.extend([
                f"📋 Products without nutrition facts: {len(update_results['products_without_nutrition'])}",
                "   (These will need nutrition data provided separately)",
                ""
            ])
        
        if update_results['errors']:
            summary_lines.extend([
                f"⚠ Errors encountered: {len(update_results['errors'])}",
                ""
            ])
        
        return "\n".join(summary_lines)
    
    def export_products_without_nutrition(self, update_results: Dict) -> str:
        """Export products without nutrition facts as CSV string"""
        if not update_results['products_without_nutrition']:
            return ""
        
        csv_lines = ["SKU,Name,Category,URL"]
        
        for product in update_results['products_without_nutrition']:
            csv_lines.append(f"{product['sku']},{product['name']},{product['category']},{product['url']}")
        
        return "\n".join(csv_lines)
    
    def extract_main_product_image(self, product_url: str) -> str:
        """
        Extract main product image URL from JSON-LD schema on product page
        """
        import requests
        import json
        import html
        import re
        from bs4 import BeautifulSoup
        
        try:
            if not product_url:
                return ""
            
            self.status_callback(f"Extracting product image from: {product_url}")
            
            # Create session with proper headers
            session = requests.Session()
            session.headers.update({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'lv,en-US;q=0.7,en;q=0.3',
                'Accept-Encoding': 'gzip, deflate',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1'
            })
            
            response = session.get(product_url)
            if response.status_code != 200:
                self.status_callback(f"Failed to fetch product page: {response.status_code}")
                return ""
            
            soup = BeautifulSoup(response.text, 'html.parser')
            # Look for JSON-LD script with Product schema
            for script in soup.find_all('script', type='application/ld+json'):
                try:
                    if script.string:
                        # Clean and parse JSON
                        json_str = html.unescape(script.string)
                        json_str = re.sub(r'\s+', ' ', json_str.replace('\\n', ' '))
                        json_str = re.sub(r'\\(["\'])', r'\1', json_str)
                        
                        data = json.loads(json_str)
                        if isinstance(data, dict) and data.get('@type') == 'Product':
                            self.status_callback("Found product data in JSON-LD schema")
                            
                            # Extract image URL from array
                            image_data = data.get('image', [])
                            if isinstance(image_data, list) and len(image_data) > 0:
                                image_url = image_data[0]
                                if image_url:
                                    self.status_callback(f"Found main product image: {image_url[:50]}...")
                                    return image_url
                            elif isinstance(image_data, str):
                                self.status_callback(f"Found main product image: {image_data[:50]}...")
                                return image_data
                
                except json.JSONDecodeError as e:
                    self.status_callback(f"Error parsing JSON-LD: {str(e)}")
                    continue
                except Exception as e:
                    self.status_callback(f"Error processing JSON-LD script: {str(e)}")
                    continue
            
            # Fallback: try to find image in HTML
            img_elem = soup.select_one('.gallery-image img, .card__image-wrapper img, .product-image img')
            if img_elem:
                image_url = img_elem.get('data-src') or img_elem.get('src')
                if image_url:
                    self.status_callback(f"Found fallback image: {image_url[:50]}...")
                    return image_url
            
            self.status_callback("No product image found")
            return ""
            
        except Exception as e:
            self.status_callback(f"Error extracting product image: {str(e)}")
            return ""
    
    def process_single_product(self, sku: str, category_code: str) -> Dict:
        """
        Process a single product by SKU - either update existing or create new
        """
        try:
            results = {
                'success': False,
                'sku': sku,
                'category_code': category_code,
                'operation': '',
                'product_data': {},
                'changes': {},
                'errors': []
            }
            
            self.status_callback(f"=== Processing Product SKU: {sku} ===")
            
            # Step 1: Check if product exists on website
            self.status_callback("Step 1: Checking product on Rimi website...")
            
            # Build product URL from SKU
            product_url = f"https://www.rimi.lv/e-veikals/lv/produkti/p/{sku}"
            
            # Try to fetch the product page
            try:
                import requests
                session = requests.Session()
                session.headers.update({
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                })
                
                response = session.get(product_url)
                if response.status_code == 404:
                    results['errors'].append("Product not found on Rimi website")
                    self.status_callback("Product not found on website")
                    return results
                elif response.status_code != 200:
                    results['errors'].append(f"Website error: {response.status_code}")
                    self.status_callback(f"Website error: {response.status_code}")
                    return results
                
                self.status_callback("Product found on website")
                
                # Extract basic product info from page
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # Get product name
                name_elem = soup.find('h1', class_='name') or soup.find('h1')
                product_name = name_elem.get_text(strip=True) if name_elem else "Unknown Product"
                
                # Get price from various possible locations
                price = "0.00"
                price_elem = soup.select_one('.price-wrapper .price, .price-tag, .price')
                if price_elem:
                    price_text = price_elem.get_text(strip=True)
                    # Extract price number - handle newlines and spaces in price format
                    import re
                    # Remove all whitespace including newlines, then look for price pattern
                    clean_text = re.sub(r'\s+', '', price_text)
                    price_match = re.search(r'(\d+[.,]?\d*)', clean_text)
                    if price_match:
                        price_str = price_match.group(1)
                        # Handle cases like "359" -> "3.59" for multi-digit prices
                        if '.' not in price_str and ',' not in price_str and len(price_str) >= 3:
                            # Insert decimal point before last 2 digits
                            price = f"{price_str[:-2]}.{price_str[-2:]}"
                        else:
                            price = price_str.replace(',', '.')
                    
                    self.status_callback(f"Price extraction: '{price_text}' -> '€{price}'")
                
                results['product_data'] = {
                    'name': product_name,
                    'price': price,
                    'url': product_url
                }
                
                self.status_callback(f"Product: {product_name} - €{price}")
                
            except Exception as e:
                results['errors'].append(f"Error fetching product: {str(e)}")
                self.status_callback(f"Error fetching product: {str(e)}")
                return results
            
            # Step 2: Check if product exists in database
            self.status_callback("Step 2: Checking product in database...")
            
            existing_product = self.db_updater.get_product_by_sku(sku)
            if existing_product:
                results['operation'] = 'update'
                self.status_callback("Product exists in database - will update")
            else:
                results['operation'] = 'create'
                self.status_callback("New product - will create")
            
            # Step 3: Extract additional product information
            self.status_callback("Step 3: Extracting product information...")
            
            # Get nutrition data
            nutrition_data = self._get_nutrition_data(product_url)
            
            # Add nutri-score information for existing products
            if results['operation'] == 'update' and existing_product:
                product_id = existing_product['product_id']
                nutri_query = """
                    SELECT nutri_score_grade, nutri_score_points 
                    FROM nutritionfacts 
                    WHERE product_id = %s
                """
                nutri_result = self.db_updater._execute_query(nutri_query, (product_id,), fetch=True)
                if nutri_result and nutri_result[0].get('nutri_score_grade'):
                    grade = nutri_result[0]['nutri_score_grade']
                    points = nutri_result[0]['nutri_score_points']
                    nutrition_data['nutri_score'] = f"{grade} ({points} points)"
                    nutrition_data['nutri_score_grade'] = grade
                    nutrition_data['nutri_score_points'] = points
            
            results['product_data']['nutrition'] = nutrition_data
            
            # Get product image
            image_url = self.extract_main_product_image(product_url)
            results['product_data']['image_url'] = image_url
            
            # Get category ID
            category_id = self._get_category_id(category_code)
            if not category_id:
                results['errors'].append(f"Invalid category code: {category_code}")
                self.status_callback(f"Invalid category code: {category_code}")
                return results
            
            results['product_data']['category_id'] = category_id
            
            # Step 4: Database operation
            self.status_callback("Step 4: Database operation...")
            
            if results['operation'] == 'update':
                # Update existing product - determine availability based on price
                is_available = float(price) > 0.0  # Price of 0.00 means unavailable
                self.status_callback(f"Price: €{price} -> Availability: {is_available}")
                success = self.db_updater.update_product_price(sku, price, is_available)
                if success:
                    # Update nutrition data if available
                    if nutrition_data['has_nutrition']:
                        product_id = existing_product['product_id']
                        self.db_updater.add_nutrition_data(product_id, nutrition_data, category_code)
                        self.status_callback("Updated nutrition data")
                    self.db_updater.save_brand_producer_data(
                        existing_product['product_id'],
                        nutrition_data.get('brand'),
                        nutrition_data.get('producer'),
                    )
                    
                    # Update photo if available
                    if image_url:
                        product_id = existing_product['product_id']
                        self.db_updater.add_product_photos(product_id, [image_url])
                        self.status_callback("Updated product photo")
                    
                    # Process ingredients for updated products
                    if nutrition_data.get('ingredients'):
                        self.db_updater.process_product_ingredients(sku, nutrition_data['ingredients'])
                        self.status_callback("Processed product ingredients")
                    
                    # Add quantity data from existing product to results
                    results['product_data']['quantity_value'] = existing_product.get('quantity_value')
                    results['product_data']['quantity_unit'] = existing_product.get('quantity_unit')
                    
                    results['success'] = True
                    results['changes'] = {
                        'price_updated': True,
                        'nutrition_updated': nutrition_data['has_nutrition'],
                        'photo_updated': bool(image_url),
                        'ingredients_processed': bool(nutrition_data.get('ingredients'))
                    }
                    self.status_callback("Product updated successfully")
                else:
                    results['errors'].append("Failed to update product price")
                    self.status_callback("Failed to update product")
            
            else:  # Create new product
                # Prepare product data for creation - determine availability based on price
                is_available = float(price) > 0.0  # Price of 0.00 means unavailable
                self.status_callback(f"New product - Price: €{price} -> Availability: {is_available}")
                product_data = {
                    'sku': sku,
                    'name': product_name,
                    'price': price,
                    'rimi_url': product_url,
                    'category_id': category_id,
                    'is_available': is_available
                }
                
                # Add quantity parsing
                quantity_value, quantity_unit = self.db_updater._parse_quantity(product_name)
                if quantity_value or quantity_unit:  # Include if either value or unit exists
                    product_data['quantity_value'] = quantity_value
                    product_data['quantity_unit'] = quantity_unit
                    # Also add to results data for Streamlit display
                    results['product_data']['quantity_value'] = quantity_value
                    results['product_data']['quantity_unit'] = quantity_unit
                    self.status_callback(f"Extracted quantity: {quantity_value} {quantity_unit}")
                
                # Create new product
                product_id = self.db_updater.add_new_product(product_data)
                if product_id:
                    self.db_updater.save_brand_producer_data(
                        product_id,
                        nutrition_data.get('brand'),
                        nutrition_data.get('producer'),
                    )
                    # Add nutrition data if available
                    if nutrition_data['has_nutrition']:
                        self.db_updater.add_nutrition_data(product_id, nutrition_data, category_code)
                        self.status_callback("Added nutrition data")
                    
                    # Add photo if available
                    if image_url:
                        self.db_updater.add_product_photos(product_id, [image_url])
                        self.status_callback("Added product photo")
                    
                    # Process ingredients for new products
                    if nutrition_data.get('ingredients'):
                        self.db_updater.process_product_ingredients(sku, nutrition_data['ingredients'])
                        self.status_callback("Processed product ingredients")
                    
                    results['success'] = True
                    results['product_data']['product_id'] = product_id
                    results['changes'] = {
                        'product_created': True,
                        'nutrition_added': nutrition_data['has_nutrition'],
                        'photo_added': bool(image_url),
                        'ingredients_processed': bool(nutrition_data.get('ingredients'))
                    }
                    self.status_callback("New product created successfully")
                else:
                    results['errors'].append("Failed to create new product")
                    self.status_callback("Failed to create product")
            
            return results
            
        except Exception as e:
            self.status_callback(f"Error processing product: {str(e)}")
            return {
                'success': False,
                'sku': sku,
                'category_code': category_code,
                'operation': '',
                'product_data': {},
                'changes': {},
                'errors': [f"Processing error: {str(e)}"]
            }

    def close(self):
        """Close all connections"""
        self.db_updater.close()
        self.ingredient_processor.close()
        self.status_callback("Update coordinator closed all connections")