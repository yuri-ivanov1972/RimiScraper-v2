"""
Robust Web Client - Handles website unavailability with retry logic and proper error handling
Implements exponential backoff and user-friendly notifications for connection issues
"""

import requests
import time
import random
from typing import Optional, Dict, Any, List
from bs4 import BeautifulSoup

class RobustWebClient:
    """Web client with robust retry logic for temporary website unavailability"""
    
    def __init__(self, status_callback=None):
        self.status_callback = status_callback or (lambda msg: print(msg))
        self.session = None
        self.last_fetch_status_code = None
        self._create_session()
    
    def _create_session(self):
        """Create session with proper headers to mimic browser"""
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'lv,en-US;q=0.7,en;q=0.3',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        })
    
    def fetch_with_retry(self, url: str, max_attempts: int = 3, base_delay: float = 2.0) -> Optional[requests.Response]:
        """
        Fetch URL with exponential backoff retry logic
        
        Args:
            url: URL to fetch
            max_attempts: Maximum number of retry attempts (default: 3)
            base_delay: Base delay in seconds for exponential backoff (default: 2.0)
            
        Returns:
            Response object if successful, None if all attempts failed
        """
        last_error = None
        self.last_fetch_status_code = None
        
        for attempt in range(max_attempts):
            try:
                self.status_callback(f"Attempt {attempt + 1}/{max_attempts}: Fetching {url}")
                
                # Add timeout to prevent hanging
                response = self.session.get(url, timeout=30)
                self.last_fetch_status_code = response.status_code
                
                if response.status_code == 200:
                    self.status_callback(f"Successfully fetched {url}")
                    return response
                elif response.status_code == 404:
                    self.status_callback(f"Product not found (404): {url}")
                    return None  # Don't retry for 404 - product doesn't exist
                else:
                    self.status_callback(f"HTTP {response.status_code} from {url}")
                    last_error = f"HTTP {response.status_code}"
                    
            except requests.exceptions.Timeout:
                last_error = "Request timeout"
                self.status_callback(f"Timeout on attempt {attempt + 1}")
                
            except requests.exceptions.ConnectionError:
                last_error = "Connection error"
                self.status_callback(f"Connection error on attempt {attempt + 1}")
                
            except requests.exceptions.RequestException as e:
                last_error = f"Request error: {str(e)}"
                self.status_callback(f"Request error on attempt {attempt + 1}: {str(e)}")
            
            # Calculate delay with exponential backoff and jitter
            if attempt < max_attempts - 1:  # Don't delay after last attempt
                delay = base_delay * (2 ** attempt) + random.uniform(0.1, 0.5)
                self.status_callback(f"Waiting {delay:.1f}s before retry...")
                time.sleep(delay)
        
        self.status_callback(f"All {max_attempts} attempts failed for {url}. Last error: {last_error}")
        return None
    
    def get_product_data(self, sku: str) -> Optional[Dict[str, Any]]:
        """
        Get product data with multiple URL pattern attempts and robust error handling
        
        Args:
            sku: Product SKU
            
        Returns:
            Dictionary with product data or None if not found
        """
        # Try different URL patterns for Rimi products
        url_patterns = [
            f"https://www.rimi.lv/e-veikals/lv/produkti/p/{sku}",
            f"https://www.rimi.lv/e-veikals/lv/products/{sku}",
            f"https://www.rimi.lv/e-veikals/en/products/{sku}",
            f"https://www.rimi.lv/products/{sku}"
        ]
        
        for pattern in url_patterns:
            self.status_callback(f"Trying URL pattern: {pattern}")
            
            response = self.fetch_with_retry(pattern)
            if response is None:
                continue  # Try next pattern
            
            try:
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # Check if this is a valid product page
                title_elem = soup.find('h1', class_='name') or soup.find('h1')
                if not title_elem:
                    self.status_callback("No product title found - trying next URL pattern")
                    continue
                
                product_name = title_elem.get_text(strip=True)
                if not product_name or product_name.lower() in ['not found', 'error', 'page not found']:
                    self.status_callback("Invalid product title - trying next URL pattern")
                    continue
                
                self.status_callback(f"Found valid product: {product_name}")
                
                # Extract all price data including price per unit and discount prices
                price_data = self._extract_all_price_data(soup)
                
                # Extract product photos
                photos = self._extract_photos(soup)

                # Brand and producer live in the embedded product-details HTML.
                from brand_producer import extract_brand_producer
                brand_producer = extract_brand_producer(soup)
                
                # Extract availability status
                is_available = self._extract_availability(soup)
                
                return {
                    'name': product_name,
                    'photos': photos,
                    'price': price_data['price'],
                    'price_per_unit': price_data['price_per_unit'],
                    'price_per_unit_type': price_data['price_per_unit_type'],
                    'discount_price': price_data['discount_price'],
                    'discount_price_per_unit': price_data['discount_price_per_unit'],
                    'is_available': is_available,
                    'brand': brand_producer['brand'],
                    'producer': brand_producer['producer'],
                    'url': pattern,
                    'soup': soup  # Include soup for further processing
                }
                
            except Exception as e:
                self.status_callback(f"Error parsing product page: {str(e)}")
                continue
        
        self.status_callback(f"Product SKU {sku} not found with any URL pattern")
        return None
    
    def _extract_price(self, soup: BeautifulSoup) -> str:
        """Extract price from product page with robust parsing"""
        price_data = self._extract_all_price_data(soup)
        return price_data.get('price', '0.00')
    
    def _extract_all_price_data(self, soup: BeautifulSoup) -> Dict:
        """
        Extract all price data from product page including:
        - Regular price
        - Price per unit (e.g., €/kg)
        - Discount price (MansRimi card)
        - Discount price per unit
        
        Returns dict with: price, price_per_unit, price_per_unit_type, discount_price, discount_price_per_unit
        """
        import re
        import json
        
        result = {
            'price': '0.00',
            'price_per_unit': None,
            'price_per_unit_type': None,
            'discount_price': None,
            'discount_price_per_unit': None
        }
        
        # Extract regular price from .price container on product page
        # Structure: <div class="price"><span>1</span><div><sup>99</sup><sub>€/gab.</sub></div></div>
        price_container = soup.select_one('div.price')
        if price_container:
            # Get euros from direct span child
            main_span = price_container.find('span', recursive=False)
            if not main_span:
                # Try any span
                main_span = price_container.find('span')
            
            sup_elem = price_container.find('sup')
            
            if main_span and sup_elem:
                euros = main_span.get_text(strip=True)
                cents = sup_elem.get_text(strip=True)
                if euros.isdigit() and cents.isdigit():
                    result['price'] = f"{euros}.{cents}"
                    self.status_callback(f"Price extracted: €{result['price']}")
        
        # Fallback: try .price-tag if .price didn't work
        if result['price'] == '0.00':
            price_tag = soup.select_one('.price-tag')
            if price_tag:
                price_text = price_tag.get_text(strip=True)
                clean_text = re.sub(r'\s+', '', price_text)
                price_match = re.search(r'(\d+[.,]?\d*)', clean_text)
                if price_match:
                    price_str = price_match.group(1)
                    if '.' not in price_str and ',' not in price_str and len(price_str) >= 3:
                        result['price'] = f"{price_str[:-2]}.{price_str[-2:]}"
                    else:
                        result['price'] = price_str.replace(',', '.')
        
        # Extract price per unit from .price-per (e.g., "7,51 €/kg")
        price_per_elem = soup.select_one('.price-per, p.price-per')
        if price_per_elem:
            price_per_text = price_per_elem.get_text(strip=True)
            per_match = re.match(r'([\d,\.]+)\s*€/(\w+)', price_per_text)
            if per_match:
                result['price_per_unit'] = per_match.group(1).replace(',', '.')
                result['price_per_unit_type'] = per_match.group(2)
                self.status_callback(f"Price per unit: {result['price_per_unit']} €/{result['price_per_unit_type']}")
        
        # Extract discount price from .price-label container
        price_label = soup.select_one('.price-label, .price-label__body')
        if price_label:
            discount_tag = price_label.select_one('.price-label__price')
            if discount_tag:
                major = discount_tag.select_one('.major')
                cents = discount_tag.select_one('.cents')
                if major:
                    major_val = major.get_text(strip=True)
                    cents_val = cents.get_text(strip=True) if cents else "00"
                    if major_val.isdigit():
                        result['discount_price'] = f"{major_val}.{cents_val}"
                        self.status_callback(f"Discount price: €{result['discount_price']}")
            
            # Extract discount price per unit from .price-per-unit
            discount_per_elem = price_label.select_one('.price-per-unit')
            if discount_per_elem:
                discount_per_text = discount_per_elem.get_text(strip=True)
                disc_match = re.match(r'([\d,\.]+)\s*€/\w+', discount_per_text)
                if disc_match:
                    result['discount_price_per_unit'] = disc_match.group(1).replace(',', '.')
                    self.status_callback(f"Discount price per unit: {result['discount_price_per_unit']}")
        
        # Schema.org fallback for main price if still 0
        if result['price'] == '0.00' or result['price'] == '0':
            schema_price = self._extract_price_from_schema(soup)
            if schema_price and schema_price != '0.00':
                self.status_callback(f"Price fallback from Schema.org: €{schema_price}")
                result['price'] = schema_price
        
        return result
    
    def _extract_price_from_schema(self, soup: BeautifulSoup) -> Optional[str]:
        """
        Extract price from Schema.org JSON-LD structured data.
        This is a fallback for geo-blocked products where HTML shows unavailable
        but the structured data still contains the real price.
        """
        import re
        import json
        
        try:
            # Find all script tags with JSON-LD data
            script_tags = soup.find_all('script', type='application/ld+json')
            
            for script in script_tags:
                try:
                    data = json.loads(script.string)
                    
                    # Check for direct Product type with offers
                    if isinstance(data, dict):
                        price = self._find_price_in_schema(data)
                        if price:
                            return price
                    
                    # Check for array of schema objects
                    elif isinstance(data, list):
                        for item in data:
                            if isinstance(item, dict):
                                price = self._find_price_in_schema(item)
                                if price:
                                    return price
                                    
                except json.JSONDecodeError:
                    continue
            
            # Also try to find price in inline scripts (non-JSON-LD structured data)
            all_scripts = soup.find_all('script')
            for script in all_scripts:
                if script.string and '"price"' in script.string:
                    # Look for offers object with price
                    match = re.search(r'"offers"\s*:\s*\{[^}]*"price"\s*:\s*["\']?(\d+\.?\d*)["\']?', script.string)
                    if match:
                        price_val = match.group(1)
                        if float(price_val) > 0:
                            return price_val
                    
                    # Direct price pattern
                    match = re.search(r'"price"\s*:\s*["\']?(\d+\.?\d*)["\']?', script.string)
                    if match:
                        price_val = match.group(1)
                        if float(price_val) > 0:
                            return price_val
                            
        except Exception as e:
            self.status_callback(f"Schema.org price extraction error: {str(e)}")
        
        return None
    
    def _find_price_in_schema(self, data: dict) -> Optional[str]:
        """Helper to find price in Schema.org data structure"""
        # Check for Offer type
        if data.get('@type') == 'Offer' and 'price' in data:
            price = str(data['price'])
            if float(price) > 0:
                return price
        
        # Check for Product type with offers
        if data.get('@type') == 'Product' and 'offers' in data:
            offers = data['offers']
            if isinstance(offers, dict) and 'price' in offers:
                price = str(offers['price'])
                if float(price) > 0:
                    return price
            elif isinstance(offers, list):
                for offer in offers:
                    if isinstance(offer, dict) and 'price' in offer:
                        price = str(offer['price'])
                        if float(price) > 0:
                            return price
        
        return None
    
    def _extract_availability(self, soup: BeautifulSoup) -> bool:
        """
        Extract product availability status from product page
        
        Args:
            soup: BeautifulSoup object of the product page
            
        Returns:
            True if product is available, False if unavailable
        """
        try:
            # Look for the unavailability message in product__main-info section
            main_info_section = soup.find('div', class_='product__main-info')
            if main_info_section:
                info_paragraph = main_info_section.find('p', class_='info')
                if info_paragraph:
                    info_text = info_paragraph.get_text(strip=True)
                    # Check for unavailability message
                    if 'Īslaicīgi nav pieejamas e-veikalā' in info_text:
                        self.status_callback("Product is UNAVAILABLE (found unavailability message)")
                        return False
            
            # If no unavailability message found, product is available
            self.status_callback("Product is AVAILABLE (no unavailability message)")
            return True
            
        except Exception as e:
            self.status_callback(f"Error extracting availability, defaulting to available: {str(e)}")
            return True  # Default to available if we can't determine
    
    def _extract_photos(self, soup: BeautifulSoup) -> List[str]:
        """
        Extract primary product photo URL from the page
        
        Args:
            soup: BeautifulSoup object of the product page
            
        Returns:
            List containing primary photo URL (single item) or empty list if not found
        """
        self.status_callback("Starting primary photo extraction...")
        
        try:
            # Priority order for finding the main product image
            primary_image_selectors = [
                # Cloudinary images (highest priority - works 100% for Rimi)
                'img[src*="cloudinary"]',
                'img[data-src*="cloudinary"]',
                
                # Main product image containers (fallback)
                '.product-image img',
                '.product__image img',
                '.product-gallery img:first-child',
                '.product-main-image img',
                
                # Rimi-specific image patterns
                'img[src*="rimibaltic.com"]',
                'img[src*="rimi.lv"][src*="product"]',
                'img[data-src*="rimibaltic.com"]',
                'img[data-src*="rimi.lv"][data-src*="product"]',
                
                # Lazy-loaded images
                'img[data-lazy*="product"]',
                'img[data-lazy*="rimi"]',
                
                # Generic product images (lower priority)
                'img[src*="product"]',
                'img[alt*="product" i]',
                'img[title*="product" i]'
            ]
            
            for selector in primary_image_selectors:
                self.status_callback(f"Trying selector: {selector}")
                
                images = soup.select(selector)
                if not images:
                    continue
                
                self.status_callback(f"Found {len(images)} images with selector '{selector}'")
                
                for img in images:
                    # Try multiple attribute sources for image URL
                    src_candidates = [
                        img.get('src'),
                        img.get('data-src'), 
                        img.get('data-lazy'),
                        img.get('data-original'),
                        img.get('data-url')
                    ]
                    
                    for src in src_candidates:
                        if not src or not isinstance(src, str):
                            continue
                            
                        # Check if this looks like a product image
                        if self._is_valid_product_image(src):
                            # Clean up the URL
                            cleaned_url = self._clean_image_url(src)
                            if cleaned_url:
                                self.status_callback(f"Successfully extracted primary photo: {cleaned_url}")
                                return [cleaned_url]  # Return only primary photo
                            else:
                                self.status_callback(f"Failed to clean image URL: {src}")
                
                self.status_callback(f"No valid images found with selector '{selector}'")
            
            # If no primary image found, log detailed failure
            self.status_callback("Failed to parse photo URL: No primary product image found with any selector")
            return []
            
        except Exception as e:
            self.status_callback(f"Failed to parse photo URL: Exception during extraction - {str(e)}")
            return []
    
    def _is_valid_product_image(self, src: str) -> bool:
        """
        Check if image URL appears to be a valid product image
        
        Args:
            src: Image source URL
            
        Returns:
            True if URL appears to be a product image
        """
        if not src:
            return False
            
        # Convert to lowercase for case-insensitive matching
        src_lower = src.lower()
        
        # Valid image file extensions
        valid_extensions = ['.jpg', '.jpeg', '.png', '.webp', '.avif']
        has_valid_extension = any(ext in src_lower for ext in valid_extensions)
        
        # Valid product image indicators
        product_indicators = [
            'product',
            'rimi',
            'rimibaltic',
            'cloudinary',
            '/images/',
            '/media/'
        ]
        has_product_indicator = any(indicator in src_lower for indicator in product_indicators)
        
        # Exclude obvious non-product images
        exclude_patterns = [
            'logo',
            'icon',
            'banner',
            'background',
            'sprite',
            'placeholder',
            'loading',
            'error',
            'default'
        ]
        is_excluded = any(pattern in src_lower for pattern in exclude_patterns)
        
        result = has_valid_extension and has_product_indicator and not is_excluded
        
        if not result:
            self.status_callback(f"Image rejected - Extension: {has_valid_extension}, Product: {has_product_indicator}, Excluded: {is_excluded}, URL: {src[:100]}")
        
        return result
    
    def _clean_image_url(self, src: str) -> str:
        """
        Clean and normalize image URL, improving Cloudinary quality for better images
        
        Args:
            src: Raw image URL
            
        Returns:
            Cleaned and optimized URL or empty string if invalid
        """
        if not src:
            return ""
            
        try:
            # Handle protocol-relative URLs
            if src.startswith('//'):
                src = 'https:' + src
            # Handle relative URLs
            elif src.startswith('/'):
                src = 'https://www.rimi.lv' + src
            
            # Basic URL validation - must start with http
            if not src.startswith(('http://', 'https://')):
                self.status_callback(f"Invalid URL protocol: {src}")
                return ""
            
            # Improve Cloudinary URL quality parameters
            if 'cloudinary' in src.lower() and 'rimibaltic' in src.lower():
                src = self._improve_cloudinary_url(src)
            
            # Remove any trailing parameters that might cause issues
            # But keep necessary CDN parameters
            if '?' in src and 'cloudinary' not in src.lower():
                src = src.split('?')[0]
            
            return src.strip()
            
        except Exception as e:
            self.status_callback(f"Error cleaning URL '{src}': {str(e)}")
            return ""
    
    def _improve_cloudinary_url(self, url: str) -> str:
        """
        Improve Cloudinary URL quality parameters for better image quality
        
        Replaces low-quality parameters (h_480,q_1,w_480) with high-quality ones (q_auto:low,w_auto)
        
        Args:
            url: Original Cloudinary URL
            
        Returns:
            Improved URL with better quality parameters
        """
        try:
            if '/upload/' not in url:
                return url
                
            # Split at upload to separate base from parameters and path
            base_part, rest = url.split('/upload/', 1)
            
            # Find the start of the path (after parameters)
            parts = rest.split('/')
            
            if len(parts) > 1:
                params_part = parts[0]
                path_part = '/'.join(parts[1:])
                
                # Replace problematic low-quality parameters
                new_params = []
                
                for param in params_part.split(','):
                    param = param.strip()
                    # Remove height, width, and low quality parameters
                    if not param.startswith(('h_', 'w_')) and param != 'q_1':
                        new_params.append(param)
                
                # Add improved quality parameters
                new_params.extend(['q_auto:low', 'w_auto'])
                
                # Reconstruct URL
                improved_url = f"{base_part}/upload/{','.join(new_params)}/{path_part}"
                self.status_callback(f"Improved image quality: {url[:60]}... -> {improved_url[:60]}...")
                return improved_url
                
            return url
            
        except Exception as e:
            self.status_callback(f"Error improving Cloudinary URL: {str(e)}")
            return url
    
    def _extract_category_from_main_page(self, soup: BeautifulSoup, nutrition_data: Dict[str, Any]) -> bool:
        """
        Extract RIMI category codes from main page HTML (breadcrumbs and product metadata)
        
        Args:
            soup: BeautifulSoup object of the main product page
            nutrition_data: Dictionary to populate with category data
            
        Returns:
            True if category was successfully extracted, False otherwise
        """
        import re
        
        # Method 1: Extract from product metadata (GTM tracking data) - Most reliable
        self.status_callback("Method 1: Searching product metadata for category...")
        try:
            page_html = str(soup)
            
            # Look for category in GTM product data: "category":"SH-7-2-17\/SH-7-2\/SH-7\/SH"
            category_patterns = [
                r'"category":\s*"([^"]*SH[^"]*)"',
                r'data-gtm-eec-product="[^"]*category[^"]*:[\s]*["\']([^"\']*SH[^"\']*)["\']',
                r'"category":\s*"([^"]*)"'
            ]
            
            for i, pattern in enumerate(category_patterns, 1):
                matches = re.findall(pattern, page_html, re.IGNORECASE)
                if matches:
                    for match in matches:
                        if 'SH-' in match:
                            # Extract rightmost RIMI code from category hierarchy
                            category_path = match.replace('\\/', '/')  # Unescape slashes
                            nutrition_data['category_path_full'] = category_path
                            
                            # Find rightmost SH-X-X-X code
                            sh_codes = re.findall(r'SH-[\d-]+', category_path)
                            if sh_codes:
                                nutrition_data['category_code'] = max(sh_codes, key=len)  # Get the most specific (longest)
                                self.status_callback(f"✓ Found category in metadata (pattern {i}): {category_path}")
                                self.status_callback(f"✓ Extracted code: {nutrition_data['category_code']}")
                                return True
                            
        except Exception as e:
            self.status_callback(f"Error in metadata extraction: {str(e)}")
        
        # Method 2: Extract from breadcrumb navigation - Backup method
        self.status_callback("Method 2: Searching breadcrumb navigation for category...")
        try:
            # Look for breadcrumb links containing SH- codes
            breadcrumb_links = soup.find_all('a', href=re.compile(r'/c/SH-'))
            
            if breadcrumb_links:
                category_codes = []
                for link in breadcrumb_links:
                    href = link.get('href', '')
                    # Extract SH-X-X-X codes from URLs like /c/SH-7-2-17
                    sh_match = re.search(r'/c/(SH-[\d-]+)', href)
                    if sh_match:
                        category_codes.append(sh_match.group(1))
                
                if category_codes:
                    # Use the most specific (longest) category code
                    most_specific = max(category_codes, key=len)
                    nutrition_data['category_code'] = most_specific
                    nutrition_data['category_path_full'] = ' / '.join(category_codes)
                    self.status_callback(f"✓ Found category in breadcrumbs: {nutrition_data['category_path_full']}")
                    self.status_callback(f"✓ Extracted code: {nutrition_data['category_code']}")
                    return True
                    
        except Exception as e:
            self.status_callback(f"Error in breadcrumb extraction: {str(e)}")
        
        # Method 3: Simple SH- pattern search in page HTML - Final fallback
        self.status_callback("Method 3: Simple SH- pattern search in page HTML...")
        try:
            page_text = soup.get_text()
            sh_codes = re.findall(r'SH-[\d-]+', page_text)
            
            if sh_codes:
                # Use the most specific (longest) code found
                most_specific = max(sh_codes, key=len)
                nutrition_data['category_code'] = most_specific
                nutrition_data['category_path_full'] = f"Pattern search result: {most_specific}"
                self.status_callback(f"✓ Found category via pattern search: {most_specific}")
                return True
                
        except Exception as e:
            self.status_callback(f"Error in pattern search: {str(e)}")
        
        self.status_callback("❌ No category codes found in main page HTML")
        return False
    
    def extract_nutrition_data(self, soup: BeautifulSoup, product_url: str) -> Dict[str, Any]:
        """
        Extract nutrition data from product page with robust HTML table parsing
        
        Args:
            soup: BeautifulSoup object of the product page
            product_url: URL of the product page for logging
            
        Returns:
            Dictionary with nutrition data
        """
        import re
        from decimal import Decimal, InvalidOperation
        
        # Initialize nutrition data
        nutrition_data = {
            'has_nutrition': False,
            'ingredients_text': '',
            'brand': None,
            'producer': None,
            'category_code': '',
            'category_path_full': '',
            'country_of_origin': 'Unknown',
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
        
        # PHASE 1 FIX: Extract category from main page HTML first
        try:
            self.status_callback("=== PHASE 1 CATEGORY EXTRACTION ===")
            category_extracted = self._extract_category_from_main_page(soup, nutrition_data)
            if category_extracted:
                self.status_callback(f"✅ Category extraction successful: {nutrition_data['category_code']}")
            else:
                self.status_callback("⚠️ No category found in main page HTML")
            self.status_callback("=" * 40)
        except Exception as e:
            self.status_callback(f"Error in category extraction: {str(e)}")
        
        try:
            from brand_producer import extract_brand_producer
            nutrition_data.update(extract_brand_producer(soup))

            # Helper function to extract decimal values
            def extract_decimal(text: str) -> float:
                try:
                    # Extract numbers from text, handling various formats
                    numbers = re.findall(r'\d+(?:[.,]\d+)?', text.replace(',', '.'))
                    return float(numbers[0]) if numbers else 0.0
                except (ValueError, AttributeError):
                    return 0.0
            
            # Helper function to extract energy values (kJ and kcal)
            def extract_energy_values(text: str) -> tuple:
                try:
                    # Match patterns like "3700 kJ/ 900 kcal" or "3700 kJ / 900 kcal"
                    pattern = r'(\d+(?:[.,]\d+)?)\s*kJ\s*[/\\]\s*(\d+(?:[.,]\d+)?)\s*kcal'
                    match = re.search(pattern, text, re.IGNORECASE)
                    if match:
                        kj = extract_decimal(match.group(1))
                        kcal = extract_decimal(match.group(2))
                        return kj, kcal
                    return 0.0, 0.0
                except Exception:
                    return 0.0, 0.0
            
            # Helper function to extract rightmost RIMI category code
            def extract_rightmost_rimi_code(category_path: str) -> str:
                """Extract rightmost RIMI category code from full path"""
                try:
                    # Split by '/' and check each part from right to left
                    parts = [part.strip() for part in category_path.split('/')]
                    for part in reversed(parts):
                        # Match RIMI category format: SH-X-X or SH-X-X-X (allow single or multiple digits)
                        if re.match(r'^SH-\d+-\d+(-\d+)?$', part):
                            return part
                    return ''
                except Exception:
                    return ''
            
            # First, try to extract from JavaScript content (existing product details)
            script_tag = None
            for script in soup.find_all('script'):
                if script.string and 'Storefront.product_details_page' in script.string:
                    script_tag = script
                    break
            
            if script_tag and script_tag.string:
                script_content = script_tag.string
                self.status_callback("Found product details script - extracting HTML content")
                
                # Extract the details tab HTML content with proper handling of escaped quotes
                # Use a more robust pattern that handles \"  inside the HTML string
                details_match = re.search(
                    r'identifier:\s*["\']details["\'],[^}]*html:\s*"((?:[^"\\]|\\.)*)"',
                    script_content, re.DOTALL
                )
                
                if details_match:
                    # Decode the HTML content with proper JSON/JavaScript string unescaping
                    import json
                    details_html = details_match.group(1)
                    
                    # Use JSON decoder which properly handles all JavaScript string escapes
                    try:
                        details_html = json.loads(f'"{details_html}"')
                        self.status_callback("Successfully decoded HTML using JSON parser")
                    except json.JSONDecodeError:
                        # Fallback to manual unescaping if JSON fails
                        self.status_callback("JSON decode failed, using manual unescaping")
                        details_html = details_html.replace('\\/', '/').replace('\\"', '"')
                        details_html = details_html.replace('\\n', '\n').replace('\\t', '\t')
                        details_html = details_html.replace('\\r', '\r')
                        # Try Unicode escape decoding, but don't fail if it errors
                        try:
                            details_html = details_html.encode('utf-8').decode('unicode_escape')
                        except (UnicodeDecodeError, AttributeError):
                            pass  # Continue with partially decoded version
                    
                    details_soup = BeautifulSoup(details_html, 'html.parser')
                    self.status_callback("Successfully parsed product details HTML with Unicode decoding")
                    
                    # Extract ingredients, category, and country of origin - SIMPLIFIED
                    ingredients_found = False
                    category_found = False
                    country_found = False
                    
                    # SIMPLE COUNTRY EXTRACTION: Search entire HTML for "Izcelsmes valsts", then get next <p> tag
                    if 'Izcelsmes valsts' in details_html:
                        self.status_callback("COUNTRY DEBUG: Found 'Izcelsmes valsts' in HTML")
                        # Find all <span> tags and check their text
                        span_count = 0
                        for span in details_soup.find_all('span'):
                            span_text = span.get_text(strip=True)
                            if 'Izcelsmes valsts' in span_text:
                                span_count += 1
                                self.status_callback(f"COUNTRY DEBUG: Found span #{span_count} with 'Izcelsmes valsts'")
                                
                                # Found the country label, now find the next <p> tag in the same parent structure
                                parent = span.parent
                                self.status_callback(f"COUNTRY DEBUG: Parent tag: {parent.name if parent else 'None'}")
                                
                                if parent:
                                    # Log parent HTML structure
                                    parent_html = str(parent)[:200]
                                    self.status_callback(f"COUNTRY DEBUG: Parent HTML: {parent_html}...")
                                    
                                    text_div = parent.find('div', class_='text')
                                    self.status_callback(f"COUNTRY DEBUG: Found text div: {text_div is not None}")
                                    
                                    if text_div:
                                        p_tag = text_div.find('p')
                                        self.status_callback(f"COUNTRY DEBUG: Found p tag: {p_tag is not None}")
                                        
                                        if p_tag:
                                            country = p_tag.get_text(strip=True)
                                            self.status_callback(f"COUNTRY DEBUG: p tag content: '{country}'")
                                            
                                            if country:
                                                nutrition_data['country_of_origin'] = country
                                                self.status_callback(f"✅ Found country of origin: {country}")
                                                country_found = True
                                                break
                                            else:
                                                self.status_callback("COUNTRY DEBUG: p tag was empty")
                                        else:
                                            self.status_callback("COUNTRY DEBUG: No p tag found in text div")
                                    else:
                                        self.status_callback("COUNTRY DEBUG: No text div found, checking siblings...")
                                        # Log all siblings
                                        for i, sibling in enumerate(parent.find_next_siblings(limit=3)):
                                            self.status_callback(f"COUNTRY DEBUG: Sibling {i}: {sibling.name} - {str(sibling)[:100]}")
                        
                        if not country_found:
                            self.status_callback(f"COUNTRY DEBUG: Checked {span_count} span(s) but no country extracted")
                    else:
                        self.status_callback("COUNTRY DEBUG: 'Izcelsmes valsts' NOT found in HTML at all")
                    
                    # Define section keywords for ingredients and category
                    ingredient_keywords = ['Sastāvdaļas', 'sastāvdaļas', 'SASTĀVDAĻAS']
                    category_keywords = ['Kategorija', 'kategorija', 'Category', 'Produkta kategorija']
                    
                    # Method 1: Look in list items with spans for ingredients and category
                    for item in details_soup.find_all('li', class_='item'):
                        span = item.find('span')
                        if span:
                            span_text = span.get_text(strip=True)
                            text_div = item.find('div', class_='text')
                            if text_div and text_div.p:
                                content = text_div.p.get_text(strip=True)
                                
                                # Check for ingredients
                                if any(keyword in span_text for keyword in ingredient_keywords):
                                    nutrition_data['ingredients_text'] = content
                                    self.status_callback(f"Found ingredients (method 1): {nutrition_data['ingredients_text'][:50]}...")
                                    ingredients_found = True
                                
                                # Check for category
                                elif any(keyword in span_text for keyword in category_keywords):
                                    nutrition_data['category_path_full'] = content
                                    nutrition_data['category_code'] = extract_rightmost_rimi_code(content)
                                    self.status_callback(f"Found category (method 1): {content} -> code: {nutrition_data['category_code']}")
                                    category_found = True
                    
                    # Method 2: Look in product list wrappers for ingredients and category only
                    for section in details_soup.find_all('div', class_='product__list-wrapper'):
                        heading = section.find('p', class_='heading')
                        if heading:
                            heading_text = heading.get_text(strip=True)
                            text_divs = section.find_all('div', class_='text')  # Find ALL text divs in this section
                            
                            # Check for ingredients
                            if not ingredients_found and any(keyword in heading_text for keyword in ingredient_keywords):
                                for text_div in text_divs:
                                    if text_div.p and text_div.p.get_text(strip=True):
                                        content = text_div.p.get_text(strip=True)
                                        nutrition_data['ingredients_text'] = content
                                        self.status_callback(f"Found ingredients (method 2, nested): {content[:80]}...")
                                        ingredients_found = True
                                        break
                            
                            # Check for category
                            elif not category_found and any(keyword in heading_text for keyword in category_keywords):
                                for text_div in text_divs:
                                    if text_div.p and text_div.p.get_text(strip=True):
                                        content = text_div.p.get_text(strip=True)
                                        nutrition_data['category_path_full'] = content
                                        nutrition_data['category_code'] = extract_rightmost_rimi_code(content)
                                        self.status_callback(f"Found category (method 2, nested): {content} -> code: {nutrition_data['category_code']}")
                                        category_found = True
                                        break
                    
                    # Method 3: Enhanced text pattern search with better regex
                    if not ingredients_found:
                        all_text = details_soup.get_text()
                        if any(keyword in all_text for keyword in ingredient_keywords):
                            # Try multiple patterns to capture different content structures
                            patterns = [
                                # Pattern 1: Content between Sastāvdaļas and next section (avoid Sastāvs which is nutrition)
                                r'Sastāvdaļas\s*([^.]*(?:\.[^.]*)*?)(?:\s*(?:Izcelsmes valsts|Sastāvs|Daudzums|$))',
                                # Pattern 2: Content after Sastāvdaļas until next capital word section  
                                r'Sastāvdaļas\s*(.*?)(?:[A-Z][a-z]+\s*[A-Z]|$)',
                                # Pattern 3: Everything after Sastāvdaļas for at least 20 characters
                                r'Sastāvdaļas\s*(.{20,}?)(?:\s*[A-Z][a-z]+|$)'
                            ]
                            
                            for i, pattern in enumerate(patterns, 1):
                                match = re.search(pattern, all_text, re.DOTALL | re.IGNORECASE)
                                if match:
                                    ingredients_text = match.group(1).strip()
                                    # Clean up the text
                                    ingredients_text = re.sub(r'\s+', ' ', ingredients_text)  # Normalize whitespace
                                    
                                    if len(ingredients_text) > 10:  # Meaningful content
                                        nutrition_data['ingredients_text'] = ingredients_text
                                        self.status_callback(f"Found ingredients (method 3, pattern {i}): {ingredients_text[:80]}...")
                                        ingredients_found = True
                                        break
                    
                    # Method 4: Fallback - extract any content near ingredient keywords 
                    if not ingredients_found:
                        all_text = details_soup.get_text()
                        for keyword in ingredient_keywords:
                            pos = all_text.find(keyword)
                            if pos != -1:
                                # Extract context after ingredient keyword
                                context_start = pos + len(keyword)
                                context_end = min(len(all_text), context_start + 200)  # Next 200 chars
                                context = all_text[context_start:context_end].strip()
                                
                                if len(context) > 15:  # Has meaningful content
                                    nutrition_data['ingredients_text'] = context
                                    self.status_callback(f"Found ingredients (method 4, context): {context[:80]}...")
                                    ingredients_found = True
                                    break
                    
                    # Method 5: Single-ingredient product fallback
                    if not ingredients_found:
                        # Try to get product name from page title or meta tags
                        page_title = ''
                        title_tag = soup.find('title')
                        if title_tag:
                            page_title = title_tag.get_text(strip=True)
                        
                        # Also try to get from h1 tags
                        if not page_title:
                            h1_tag = soup.find('h1')
                            if h1_tag:
                                page_title = h1_tag.get_text(strip=True)
                        
                        if page_title:
                            # Helper function to normalize text for matching (remove diacritics)
                            def normalize_text(text):
                                replacements = {
                                    'ā': 'a', 'ē': 'e', 'ī': 'i', 'ū': 'u', 'ō': 'o', 
                                    'ģ': 'g', 'ķ': 'k', 'ļ': 'l', 'ņ': 'n', 'š': 's', 'ž': 'z',
                                    'č': 'c'
                                }
                                normalized = text.lower()
                                for latvian, ascii_char in replacements.items():
                                    normalized = normalized.replace(latvian, ascii_char)
                                return normalized
                            
                            # Canonical ingredient mapping for single-ingredient products
                            ingredient_patterns = {
                                # Eggs - various forms
                                r'\b(?:olas?|olu|egg|eggs)\b': 'olas',
                                # Milk  
                                r'\b(?:piens|milk)\b': 'piens',
                                # Bread
                                r'\b(?:maize|bread|maizes)\b': 'maize',
                                # Cheese
                                r'\b(?:siers|cheese|siera)\b': 'siers',
                                # Meat - various forms
                                r'\b(?:gala|galas|meat)\b': 'gaļa',
                                # Fish - various forms  
                                r'\b(?:zivs|zivis|fish)\b': 'zivs'
                            }
                            
                            # Normalize title for matching
                            normalized_title = normalize_text(page_title)
                            
                            # Try each ingredient pattern
                            for pattern, canonical_ingredient in ingredient_patterns.items():
                                if re.search(pattern, normalized_title, re.IGNORECASE):
                                    nutrition_data['ingredients_text'] = canonical_ingredient
                                    self.status_callback(f"Inferred single ingredient from product title: {canonical_ingredient} (matched pattern in '{page_title}')")
                                    ingredients_found = True
                                    break
                    
                    # Method 3: Category extraction fallback - comprehensive text pattern search
                    if not category_found:
                        all_text = details_soup.get_text()
                        if any(keyword in all_text for keyword in category_keywords):
                            # Try multiple patterns to capture different category content structures
                            category_patterns = [
                                # Pattern 1: Category followed by path with RIMI codes
                                r'(?:Kategorija|Category)\s*:?\s*([^.]*(?:\bSH-\d+-\d+(?:-\d+)?\b)[^.]*)',
                                # Pattern 2: Any line containing category keyword and RIMI code
                                r'([^.\n]*(?:Kategorija|Category)[^.\n]*(?:\bSH-\d+-\d+(?:-\d+)?\b)[^.\n]*)',
                                # Pattern 3: RIMI code with surrounding context mentioning category
                                r'([^.\n]*(?:\bSH-\d+-\d+(?:-\d+)?\b)[^.\n]*(?:Kategorija|Category)[^.\n]*)',
                                # Pattern 4: Just extract any RIMI code in category context
                                r'(?:Kategorija|Category)[^.]*?(\bSH-\d+-\d+(?:-\d+)?\b)'
                            ]
                            
                            for i, pattern in enumerate(category_patterns, 1):
                                match = re.search(pattern, all_text, re.DOTALL | re.IGNORECASE)
                                if match:
                                    content = match.group(1).strip()
                                    # Clean up the text
                                    content = re.sub(r'\s+', ' ', content)  # Normalize whitespace
                                    
                                    if len(content) > 3:  # Meaningful content
                                        nutrition_data['category_path_full'] = content
                                        nutrition_data['category_code'] = extract_rightmost_rimi_code(content)
                                        self.status_callback(f"Found category (method 3, pattern {i}): {content} -> code: {nutrition_data['category_code']}")
                                        category_found = True
                                        break
                    
                    # Method 4: Category proximity fallback - extract context around category keywords
                    if not category_found:
                        all_text = details_soup.get_text()
                        for keyword in category_keywords:
                            pos = all_text.find(keyword)
                            if pos != -1:
                                # Extract context after category keyword
                                context_start = pos + len(keyword)
                                context_end = min(len(all_text), context_start + 300)  # Next 300 chars
                                context = all_text[context_start:context_end].strip()
                                
                                # Look for RIMI code in context
                                rimi_match = re.search(r'\bSH-\d+-\d+(?:-\d+)?\b', context)
                                if rimi_match and len(context) > 10:  # Has meaningful content with RIMI code
                                    nutrition_data['category_path_full'] = context[:100]  # Limit to 100 chars
                                    nutrition_data['category_code'] = rimi_match.group(0)
                                    self.status_callback(f"Found category (method 4, proximity): {context[:50]}... -> code: {nutrition_data['category_code']}")
                                    category_found = True
                                    break
                    
                    # Find nutrition table with proper HTML parsing and character encoding handling
                    tables = details_soup.find_all('table')
                    nutrition_table = None
                    for table in tables:
                        headers = table.find_all('th')
                        # Check for nutrition headers with proper Unicode handling
                        for header in headers:
                            header_text = header.get_text(strip=True)
                            # Handle both Unicode escaped and normal Latvian characters
                            if any(pattern in header_text.lower() for pattern in ['uzturvērtība', 'uzturv\\u0113rt\\u012bba', 'nutrition']):
                                nutrition_table = table
                                self.status_callback("Found nutrition table with structured data")
                                break
                        if nutrition_table:
                            break
                    
                    if nutrition_table:
                        nutrition_data['has_nutrition'] = True
                        found_nutrition_count = 0
                        
                        for row in nutrition_table.find_all('tr'):
                            cells = row.find_all(['td'])
                            if len(cells) >= 2:
                                label = cells[0].get_text(strip=True).lower()
                                value = cells[1].get_text(strip=True)
                                
                                self.status_callback(f"Processing nutrition row: '{label}' -> '{value}'")
                                
                                # Handle Unicode escape sequences in Latvian text
                                if any(pattern in label for pattern in ['enerģētiskā vērtība', 'ener\\u0123\\u0113tisk\\u0101 v\\u0113rt\\u012bba', 'energy']):
                                    kj, kcal = extract_energy_values(value)
                                    if kj > 0 or kcal > 0:
                                        nutrition_data['energy_kj'] = kj
                                        nutrition_data['energy_kcal'] = kcal
                                        found_nutrition_count += 2
                                        self.status_callback(f"✓ Energy: {kcal} kcal ({kj} kJ)")
                                
                                elif ('tauki' in label or 'fat' in label) and not any(x in label for x in ['piesātinātās', 'pies\\u0101tin\\u0101t\\u0101s', 'tostarp', 'saturated']):
                                    fat_total = extract_decimal(value)
                                    nutrition_data['fat_total'] = fat_total
                                    found_nutrition_count += 1
                                    self.status_callback(f"✓ Fat total: {fat_total}g")
                                
                                elif any(pattern in label for pattern in ['piesātinātās taukskābes', 'pies\\u0101tin\\u0101t\\u0101s tauksk\\u0101bes', 'tostarp piesātinātās', 'saturated']):
                                    fat_saturated = extract_decimal(value)
                                    nutrition_data['fat_saturated'] = fat_saturated
                                    found_nutrition_count += 1
                                    self.status_callback(f"✓ Saturated fat: {fat_saturated}g")
                                
                                elif any(pattern in label for pattern in ['ogļhidrāti', 'og\\u013chidr\\u0101ti', 'carbohydrate']) and not any(x in label for x in ['cukuri', 'tostarp', 'sugar']):
                                    carbs_total = extract_decimal(value)
                                    nutrition_data['carbs_total'] = carbs_total
                                    found_nutrition_count += 1
                                    self.status_callback(f"✓ Carbohydrates: {carbs_total}g")
                                
                                elif any(pattern in label for pattern in ['cukuri', 'tostarp cukuri', 'sugar']):
                                    carbs_sugars = extract_decimal(value)
                                    nutrition_data['carbs_sugars'] = carbs_sugars
                                    found_nutrition_count += 1
                                    self.status_callback(f"✓ Sugars: {carbs_sugars}g")
                                
                                elif any(pattern in label for pattern in ['olbaltumvielas', 'protein']):
                                    protein = extract_decimal(value)
                                    nutrition_data['protein'] = protein
                                    found_nutrition_count += 1
                                    self.status_callback(f"✓ Protein: {protein}g")
                                
                                elif any(pattern in label for pattern in ['sāls', 's\\u0101ls', 'salt']):
                                    salt = extract_decimal(value)
                                    nutrition_data['salt'] = salt
                                    found_nutrition_count += 1
                                    self.status_callback(f"✓ Salt: {salt}g")
                                
                                elif any(pattern in label for pattern in ['šķiedrvielas', 'fiber']):
                                    fiber = extract_decimal(value)
                                    nutrition_data['fiber'] = fiber
                                    found_nutrition_count += 1
                                    self.status_callback(f"✓ Fiber: {fiber}g")
                        
                        self.status_callback(f"Nutrition table parsing complete: {found_nutrition_count} values extracted")
                        
                        if found_nutrition_count >= 3:
                            self.status_callback(f"✓ Complete nutrition data found ({found_nutrition_count} values)")
                        else:
                            self.status_callback(f"○ Partial nutrition data ({found_nutrition_count} values found)")
                    else:
                        self.status_callback("○ No nutrition table found in product details")
                else:
                    self.status_callback("○ Could not extract details HTML from script")
            else:
                self.status_callback("○ No product details script found")
                
        except Exception as e:
            self.status_callback(f"✗ Error extracting nutrition data: {str(e)}")
        
        # Add backwards compatibility for older code expecting 'ingredients' key
        nutrition_data['ingredients'] = nutrition_data.get('ingredients_text', '')
        
        return nutrition_data
    
    def close(self):
        """Close the session"""
        if self.session:
            self.session.close()