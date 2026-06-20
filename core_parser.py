#!/usr/bin/env python3
"""
Core parsing functionality for Rimi website
- Category page parsing with pagination
- Product page parsing
- Database connections using exact hierarchical matching
"""
import requests
from bs4 import BeautifulSoup
import re
import time
import random
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
import psycopg2
from psycopg2.extras import RealDictCursor
import os
import json

@dataclass
class ProductInfo:
    sku: str
    name: str
    price: Optional[str]
    url: str
    price_per_unit: Optional[str] = None
    price_per_unit_type: Optional[str] = None
    discount_price: Optional[str] = None
    discount_price_per_unit: Optional[str] = None
    is_available: bool = True

class RimiParser:
    def __init__(self, status_callback=None):
        self.status_callback = status_callback or (lambda x: None)
        self.session = self._create_session()
        
    def _create_session(self) -> requests.Session:
        """Create session with headers to mimic a Latvian browser"""
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'lv-LV,lv;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Referer': 'https://www.rimi.lv/',
        })
        return session
    
    def build_category_url(self, category_code: str) -> str:
        """Build Rimi category URL from category code"""
        category_code = category_code.strip().upper()
        if not category_code.startswith('SH-'):
            category_code = f"SH-{category_code}"
        return f"https://www.rimi.lv/e-veikals/lv/produkti/c/{category_code}"
    
    def _detect_page_size(self, category_url: str, soup: BeautifulSoup = None) -> int:
        """Dynamically detect page size by counting products on first page"""
        try:
            if soup is None:
                response = self.session.get(category_url, timeout=10)
                soup = BeautifulSoup(response.content, 'html.parser')
            
            # Count actual products on first page
            products_on_first_page = len(self.extract_products_from_page(category_url, max_products=100))
            self.status_callback(f"Found {products_on_first_page} products on first page")
            
            # Common page sizes used by e-commerce sites
            common_page_sizes = [20, 24, 25, 30, 36, 40, 48, 50, 60]
            
            # If we found products, try to match to common page sizes
            if products_on_first_page > 0:
                # If it matches a common page size exactly, use it
                if products_on_first_page in common_page_sizes:
                    self.status_callback(f"Detected standard page size: {products_on_first_page}")
                    return products_on_first_page
                # If it's close to a common page size (within 2), use the common one
                for page_size in common_page_sizes:
                    if abs(products_on_first_page - page_size) <= 2:
                        self.status_callback(f"Detected page size {products_on_first_page}, using standard {page_size}")
                        return page_size
                # Otherwise, use the actual count
                self.status_callback(f"Using actual detected page size: {products_on_first_page}")
                return products_on_first_page
            
            # Fallback: default to 40 (current Rimi standard)
            self.status_callback("No products detected, using fallback page size: 40")
            return 40
            
        except Exception as e:
            self.status_callback(f"Error detecting page size, using fallback: {str(e)}")
            return 40  # Safe fallback
    
    def get_total_products_from_pagination(self, category_url: str) -> Tuple[int, int]:
        """Get exact product count by checking the last page and dynamically detecting page size"""
        try:
            self.status_callback(f"Fetching category page: {category_url}")
            response = self.session.get(category_url, timeout=10)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # First, get actual product count on first page (before any rounding)
            actual_first_page_count = len(self.extract_products_from_page(category_url, max_products=100))
            self.status_callback(f"Extracted {actual_first_page_count} products from page")
            
            # Then detect the page size (may be rounded for multi-page categories)
            page_size = self._detect_page_size(category_url, soup)
            self.status_callback(f"Detected page size: {page_size} products per page")
            
            max_page = 1
            
            # Method 1: Look for Rimi's specific pagination structure
            pagination_container = soup.find('div', class_='pagination')
            if pagination_container:
                # Get all page numbers from pagination links
                visible_page_links = pagination_container.find_all('a')
                visible_pages = []
                for link in visible_page_links:
                    text = link.get_text(strip=True)
                    if text.isdigit() and 1 <= int(text) <= 200:
                        visible_pages.append(int(text))
                
                if visible_pages:
                    # Check if we have a gap in pagination (like 2, 3, 72)
                    sorted_pages = sorted(set(visible_pages))
                    self.status_callback(f"Found visible page numbers: {sorted_pages}")
                    
                    # If there's a large gap (> 5 pages), the highest number might be incorrect
                    if len(sorted_pages) >= 2:
                        gaps = [sorted_pages[i+1] - sorted_pages[i] for i in range(len(sorted_pages)-1)]
                        max_gap = max(gaps) if gaps else 0
                        
                        # Even with gaps in pagination display, use the highest page number found
                        max_page = max(visible_pages)
                        if max_gap > 10:
                            self.status_callback(f"Large gap in pagination display ({max_gap} pages) - this may be normal pagination UI behavior")
                    else:
                        max_page = max(visible_pages)
                else:
                    # Fallback to data-page attributes
                    page_links = pagination_container.find_all('a', attrs={'data-page': True})
                    if page_links:
                        page_numbers = []
                        for link in page_links:
                            page_num = link.get('data-page')
                            if page_num and page_num.isdigit():
                                page_numbers.append(int(page_num))
                        if page_numbers:
                            max_page = max(page_numbers)
                            self.status_callback(f"Found pagination with pages: {sorted(page_numbers)}")
            
            # Method 2: Fallback - look for any numeric pagination links
            if max_page == 1:
                pagination_links = soup.find_all('a', href=re.compile(r'currentPage=\d+'))
                for link in pagination_links:
                    href = link.get('href', '')
                    page_match = re.search(r'currentPage=(\d+)', href)
                    if page_match:
                        page_num = int(page_match.group(1))
                        max_page = max(max_page, page_num)
            
            # Method 3: Look for numeric text in pagination elements
            if max_page == 1:
                pagination_elements = soup.find_all(['a', 'span'], class_=re.compile(r'pagination'))
                for element in pagination_elements:
                    text = element.get_text(strip=True)
                    if text.isdigit() and 1 <= int(text) <= 100:
                        page_num = int(text)
                        max_page = max(max_page, page_num)
            
            # Now get exact product count using detected page size
            if max_page == 1:
                # Single page - use the actual count from first page (don't re-fetch)
                total_products = actual_first_page_count
                self.status_callback(f"Single page with {total_products} products")
            else:
                # Multiple pages - validate last page and get exact count
                self.status_callback(f"Validating last page ({max_page}) contains products")
                last_page_url = f"{category_url}?pageSize={page_size}&currentPage={max_page}"
                
                products_on_last_page = len(self.extract_products_from_page(last_page_url, max_products=page_size * 2))
                
                # If the detected last page is empty, search backwards for the real last page
                if products_on_last_page == 0:
                    self.status_callback(f"Page {max_page} is empty, searching for actual last page")
                    actual_last_page = max_page
                    
                    # Search backwards from detected max_page
                    for test_page in range(max_page - 1, max(1, max_page - 10), -1):
                        test_url = f"{category_url}?pageSize={page_size}&currentPage={test_page}"
                        test_products = len(self.extract_products_from_page(test_url, max_products=page_size * 2))
                        if test_products > 0:
                            actual_last_page = test_page
                            products_on_last_page = test_products
                            self.status_callback(f"Found actual last page: {actual_last_page} with {test_products} products")
                            break
                    
                    max_page = actual_last_page
                
                # Calculate exact total using detected page size
                total_products = (max_page - 1) * page_size + products_on_last_page
                self.status_callback(f"Exact count: ({max_page}-1) × {page_size} + {products_on_last_page} = {total_products} products")
            
            return total_products, max_page
            
        except Exception as e:
            self.status_callback(f"Error getting pagination info: {str(e)}")
            return 0, 0
    
    def extract_products_from_page(self, page_url: str, max_products: int = 100) -> List[ProductInfo]:
        """Extract product information from a single page"""
        products = []
        
        try:
            self.status_callback(f"Fetching products from: {page_url}")
            response = self.session.get(page_url, timeout=10)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Priority 1: Look for Rimi-specific product containers with data-product-code
            product_elements = soup.select('div[data-product-code]')[:max_products]
            
            if not product_elements:
                # Fallback: Look for generic product containers
                product_selectors = [
                    'div[class*="product"]',
                    'article[class*="product"]',
                    'div[class*="item"]',
                    '[data-testid*="product"]'
                ]
                
                for selector in product_selectors:
                    elements = soup.select(selector)
                    if elements:
                        product_elements = elements[:max_products]
                        break
            
            for element in product_elements:
                try:
                    # Extract SKU - Priority 1: data-product-code attribute (Rimi specific)
                    sku = element.get('data-product-code')
                    
                    # Fallback: Extract from URL if data-product-code not found
                    if not sku:
                        link = element.find('a', href=True)
                        if link and link.get('href'):
                            href = link.get('href')
                            # Ensure href is a string
                            if isinstance(href, str):
                                # Extract SKU from URL pattern like /p/123456
                                sku_match = re.search(r'/p/(\d+)', href)
                                if sku_match:
                                    sku = sku_match.group(1)
                    
                    # Build product URL
                    product_url = ""
                    link = element.find('a', href=True)
                    if link and link.get('href'):
                        href = link.get('href')
                        # Ensure href is a string
                        if isinstance(href, str):
                            if href.startswith('/'):
                                product_url = f"https://www.rimi.lv{href}"
                            else:
                                product_url = href
                    
                    # Extract product name
                    name_selectors = ['p.card__name', 'h3', 'h4', '[class*="title"]', '[class*="name"]']
                    name = ""
                    for selector in name_selectors:
                        name_elem = element.select_one(selector)
                        if name_elem:
                            name = name_elem.get_text(strip=True)
                            break
                    
                    # Extract price - Method 1: HTML price structure (most reliable)
                    # Regular price from card__price-wrapper container
                    price = ""
                    price_per_unit = None
                    price_per_unit_type = None
                    discount_price = None
                    discount_price_per_unit = None
                    
                    price_wrapper = element.select_one('.card__price-wrapper')
                    if price_wrapper:
                        # Extract regular price from .price-tag.card__price
                        price_tag = price_wrapper.select_one('.price-tag')
                        if price_tag:
                            price_parts = []
                            # Prefer aria-hidden span (visible digits only) over sr-only span
                            # which contains full text like "1.45 € par gab." that breaks parsing
                            main_span = price_tag.find('span', attrs={'aria-hidden': 'true'})
                            if not main_span:
                                main_span = price_tag.find('span')
                            if main_span:
                                price_parts.append(main_span.get_text(strip=True))
                            
                            sup_elem = price_tag.find('sup')
                            if sup_elem:
                                price_parts.append(sup_elem.get_text(strip=True))
                            
                            if len(price_parts) >= 2:
                                price = f"€{price_parts[0]}.{price_parts[1]}"
                            elif len(price_parts) == 1:
                                price = f"€{price_parts[0]}"
                        
                        # Extract price per unit from .card__price-per (e.g., "4,02 €/kg")
                        price_per_elem = price_wrapper.select_one('.card__price-per')
                        if price_per_elem:
                            # Prefer aria-hidden span; fall back to full text
                            price_per_visible = price_per_elem.find('span', attrs={'aria-hidden': 'true'})
                            price_per_text = price_per_visible.get_text(strip=True) if price_per_visible else price_per_elem.get_text(strip=True)
                            # Use re.search (not re.match) in case sr-only text precedes the number
                            per_match = re.search(r'([\d,\.]+)\s*€/(\w+)', price_per_text)
                            if per_match:
                                price_per_unit = per_match.group(1).replace(',', '.')
                                price_per_unit_type = per_match.group(2)
                    
                    # Fallback: try .price-tag directly if no wrapper found
                    if not price:
                        price_tag = element.select_one('.price-tag')
                        if price_tag:
                            price_parts = []
                            main_span = price_tag.find('span', attrs={'aria-hidden': 'true'})
                            if not main_span:
                                main_span = price_tag.find('span')
                            if main_span:
                                price_parts.append(main_span.get_text(strip=True))
                            
                            sup_elem = price_tag.find('sup')
                            if sup_elem:
                                price_parts.append(sup_elem.get_text(strip=True))
                            
                            if len(price_parts) >= 2:
                                price = f"€{price_parts[0]}.{price_parts[1]}"
                            elif len(price_parts) == 1:
                                price = f"€{price_parts[0]}"
                    
                    # Extract discount price from price-label container
                    price_label = element.select_one('.price-label')
                    if price_label:
                        discount_tag = price_label.select_one('.price-label__price')
                        if discount_tag:
                            # Extract discount price from .major and .cents
                            major = discount_tag.select_one('.major')
                            cents = discount_tag.select_one('.cents')
                            if major:
                                major_val = major.get_text(strip=True)
                                cents_val = cents.get_text(strip=True) if cents else "00"
                                discount_price = f"€{major_val}.{cents_val}"
                        
                        # Extract discount price per unit from .price-per-unit
                        discount_per_elem = price_label.select_one('.price-per-unit')
                        if discount_per_elem:
                            discount_per_visible = discount_per_elem.find('span', attrs={'aria-hidden': 'true'})
                            discount_per_text = discount_per_visible.get_text(strip=True) if discount_per_visible else discount_per_elem.get_text(strip=True)
                            # Use re.search so sr-only prefix text doesn't block the match
                            disc_match = re.search(r'([\d,\.]+)\s*€/\w+', discount_per_text)
                            if disc_match:
                                discount_price_per_unit = disc_match.group(1).replace(',', '.')
                    
                    # Method 2: Fallback to JSON data attribute
                    if not price:
                        gtm_data = element.get('data-gtm-eec-product')
                        if gtm_data:
                            try:
                                product_data = json.loads(gtm_data)
                                if 'price' in product_data:
                                    price = f"€{product_data['price']}"
                            except:
                                pass
                    
                    # Method 3: Simple fallback
                    if not price:
                        price_elem = element.select_one('[class*="price"]')
                        if price_elem:
                            price = price_elem.get_text(strip=True)
                    
                    # Check availability - product is unavailable if it has "show similar products"
                    # button AND has no price. Requiring both conditions avoids false negatives
                    # caused by geo-restricted responses where the button may appear even for
                    # products that are genuinely in stock.
                    is_available = True
                    similar_btn = element.select_one('.js-open-similar-products')
                    if similar_btn and not price:
                        is_available = False
                    
                    if sku and name:
                        products.append(ProductInfo(
                            sku=sku,
                            name=name,
                            price=price,
                            url=product_url,
                            price_per_unit=price_per_unit,
                            price_per_unit_type=price_per_unit_type,
                            discount_price=discount_price,
                            discount_price_per_unit=discount_price_per_unit,
                            is_available=is_available
                        ))
                
                except Exception as e:
                    continue  # Skip problematic products
            
            self.status_callback(f"Extracted {len(products)} products from page")
            return products
            
        except Exception as e:
            self.status_callback(f"Error extracting products: {str(e)}")
            return []
    
    def collect_category_skus(self, category_code: str) -> List[str]:
        """
        Collect all product SKUs from a Rimi category using pagination
        
        Args:
            category_code: Rimi category code (e.g., 'SH-7-2-14')
            
        Returns:
            List of unique SKU strings found in the category
        """
        try:
            # Build category URL using existing normalization method
            category_url = self.build_category_url(category_code)
            self.status_callback(f"Collecting SKUs from category {category_code}")
            self.status_callback(f"Category URL: {category_url}")
            
            # Get pagination info and detect actual page size
            total_products, total_pages = self.get_total_products_from_pagination(category_url)
            
            if total_products == 0:
                self.status_callback(f"No products found in category {category_code}")
                return []
            
            # Detect actual page size used by the site
            page_size = self._detect_page_size(category_url)
            self.status_callback(f"Detected page size: {page_size} products per page")
            self.status_callback(f"Found {total_products} products across {total_pages} pages in category {category_code}")
            
            # Collect SKUs from all pages
            all_skus = []
            successful_pages = 0
            
            for page_num in range(1, total_pages + 1):
                try:
                    # For single-page categories, don't limit page size to avoid losing products
                    # For multi-page categories, use standard pagination with detected page size
                    if total_pages == 1:
                        # Single page - fetch without pageSize limit to get all products
                        page_url = category_url
                        max_products_to_extract = total_products + 10  # Use actual count + buffer
                    else:
                        # Multi-page - use standard pagination
                        page_url = f"{category_url}?pageSize={page_size}&currentPage={page_num}"
                        max_products_to_extract = page_size * 2
                    
                    self.status_callback(f"Processing page {page_num}/{total_pages}: {page_url}")
                    
                    # Extract products from this page
                    products = self.extract_products_from_page(page_url, max_products=max_products_to_extract)
                    
                    # Collect SKUs from products
                    page_skus = [product.sku for product in products if product.sku]
                    all_skus.extend(page_skus)
                    successful_pages += 1
                    
                    self.status_callback(f"Page {page_num}: Found {len(page_skus)} SKUs")
                    
                except Exception as page_error:
                    self.status_callback(f"Error processing page {page_num}: {str(page_error)} - Skipping")
                    continue
            
            # Deduplicate SKUs while preserving order
            unique_skus = list(dict.fromkeys(all_skus))  # Preserves order, removes duplicates
            
            self.status_callback(f"Category {category_code} collection complete:")
            self.status_callback(f"  - Total pages processed: {successful_pages}/{total_pages}")
            self.status_callback(f"  - Total SKUs found: {len(all_skus)} (including duplicates)")
            self.status_callback(f"  - Unique SKUs: {len(unique_skus)}")
            
            # Handle count mismatch with retry logic
            if len(unique_skus) != total_products and successful_pages == total_pages:
                self.status_callback(f"⚠️  SKU count mismatch: Expected {total_products}, got {len(unique_skus)}")
                self.status_callback(f"Attempting to find actual last page to verify count...")
                
                # Try to find the actual last page to verify our pagination
                actual_last_page = self._find_actual_last_page(category_url, total_pages, page_size)
                if actual_last_page != total_pages:
                    self.status_callback(f"Found different last page: {actual_last_page} vs {total_pages}")
                    # Note: Could implement retry here if needed, but for now just log the finding
            
            return unique_skus
            
        except Exception as e:
            self.status_callback(f"Error collecting SKUs from category {category_code}: {str(e)}")
            return []
    
    def _find_actual_last_page(self, category_url: str, suspected_max: int, page_size: int = 40) -> int:
        """Use binary search to find the actual last page with products"""
        
        # Start with a reasonable upper bound
        left, right = 1, min(suspected_max, 100)  # Cap at 100 to avoid infinite loops
        actual_last_page = 1
        
        self.status_callback(f"Binary searching for last page between 1 and {right} (page size: {page_size})")
        
        # Binary search for the last page with products
        while left <= right:
            mid = (left + right) // 2
            test_url = f"{category_url}?pageSize={page_size}&currentPage={mid}"
            
            try:
                products_count = len(self.extract_products_from_page(test_url, max_products=page_size * 2))
                
                if products_count > 0:
                    actual_last_page = mid
                    left = mid + 1  # Search for higher pages
                    self.status_callback(f"Page {mid}: {products_count} products - searching higher")
                else:
                    right = mid - 1  # This page is empty, search lower
                    self.status_callback(f"Page {mid}: 0 products - searching lower")
                    
            except Exception:
                right = mid - 1  # Treat errors as empty pages
                
        self.status_callback(f"Binary search found actual last page: {actual_last_page}")
        return actual_last_page
    
    def collect_category_products(self, category_code: str) -> List[ProductInfo]:
        """
        Collect all products with prices from a Rimi category using pagination.
        Returns full ProductInfo objects including price data for incremental updates.
        
        Args:
            category_code: Rimi category code (e.g., 'SH-7-2-14')
            
        Returns:
            List of ProductInfo objects with sku, name, price, and url
        """
        try:
            category_url = self.build_category_url(category_code)
            self.status_callback(f"Collecting products with prices from category {category_code}")
            
            total_products, total_pages = self.get_total_products_from_pagination(category_url)
            
            if total_products == 0:
                self.status_callback(f"No products found in category {category_code}")
                return []
            
            page_size = self._detect_page_size(category_url)
            self.status_callback(f"Found {total_products} products across {total_pages} pages")
            
            all_products = []
            seen_skus = set()
            
            for page_num in range(1, total_pages + 1):
                try:
                    if total_pages == 1:
                        page_url = category_url
                        max_products_to_extract = total_products + 10
                    else:
                        page_url = f"{category_url}?pageSize={page_size}&currentPage={page_num}"
                        max_products_to_extract = page_size * 2
                    
                    self.status_callback(f"Processing page {page_num}/{total_pages}")
                    
                    products = self.extract_products_from_page(page_url, max_products=max_products_to_extract)
                    
                    for product in products:
                        if product.sku and product.sku not in seen_skus:
                            seen_skus.add(product.sku)
                            all_products.append(product)
                    
                    self.status_callback(f"Page {page_num}: Found {len(products)} products")
                    
                except Exception as page_error:
                    self.status_callback(f"Error processing page {page_num}: {str(page_error)} - Skipping")
                    continue
            
            self.status_callback(f"Category {category_code} complete: {len(all_products)} unique products with prices")
            return all_products
            
        except Exception as e:
            self.status_callback(f"Error collecting products from category {category_code}: {str(e)}")
            return []

class DatabaseConnection:
    """Database connection manager using exact hierarchical matching"""
    
    def __init__(self):
        from database_config import db_config
        self.categories_db_url = db_config.categories_db_url
        self.products_db_url = db_config.products_db_url
    
    def get_categories(self) -> List[Dict]:
        """Get all categories from normalized_categories table"""
        try:
            conn = psycopg2.connect(self.categories_db_url)
            conn.autocommit = True
            
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT category_id, rimi_category_code, name_lv, name_en, 
                           parent_category_id, level
                    FROM normalized_categories 
                    ORDER BY level, rimi_category_code;
                """)
                return cur.fetchall()
                
        except Exception as e:
            print(f"Error getting categories: {str(e)}")
            return []
        finally:
            if 'conn' in locals():
                conn.close()
    
    def get_subcategories(self, category_code: str) -> List[Dict]:
        """Get all subcategories for a given category using hierarchical structure"""
        try:
            conn = psycopg2.connect(self.categories_db_url)
            conn.autocommit = True
            
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # First, find the target category and its level
                cur.execute("""
                    SELECT category_id, rimi_category_code, level, parent_category_id
                    FROM normalized_categories 
                    WHERE rimi_category_code = %s;
                """, (category_code,))
                target_category = cur.fetchone()
                
                if not target_category:
                    return []
                
                # If level < 3, find all subcategories recursively
                if target_category['level'] < 3:
                    cur.execute("""
                        WITH RECURSIVE category_tree AS (
                            -- Start with the target category
                            SELECT category_id, rimi_category_code, parent_category_id, level, name_lv
                            FROM normalized_categories 
                            WHERE category_id = %s
                            
                            UNION ALL
                            
                            -- Find all children recursively
                            SELECT nc.category_id, nc.rimi_category_code, nc.parent_category_id, nc.level, nc.name_lv
                            FROM normalized_categories nc
                            INNER JOIN category_tree ct ON nc.parent_category_id = ct.category_id
                        )
                        SELECT category_id, rimi_category_code, level, name_lv
                        FROM category_tree
                        ORDER BY level, rimi_category_code;
                    """, (target_category['category_id'],))
                    
                    all_categories = cur.fetchall()
                    return all_categories
                else:
                    # If level = 3, just return the category itself
                    return [target_category]
                
        except Exception as e:
            print(f"Error getting subcategories: {str(e)}")
            return []
        finally:
            if 'conn' in locals():
                conn.close()
    
    def get_products_for_category(self, category_code: str) -> List[Dict]:
        """Get products from external database using exact hierarchical matching"""
        try:
            # Get all subcategories for the given category using hierarchical structure
            subcategories = self.get_subcategories(category_code)
            
            if not subcategories:
                return []
            
            # Extract category IDs for product lookup
            category_ids = [cat['category_id'] for cat in subcategories]
            
            # Get products for these categories
            conn = psycopg2.connect(self.products_db_url)
            conn.autocommit = True
            
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Use exact category_id matching
                if len(category_ids) == 1:
                    cur.execute("""
                        SELECT product_id, sku, name, rimi_url, category_id,
                               quantity_value, quantity_unit, name_norm
                        FROM products 
                        WHERE category_id = %s
                        ORDER BY name;
                    """, (category_ids[0],))
                else:
                    # Use IN clause for multiple category IDs
                    placeholders = ','.join(['%s'] * len(category_ids))
                    cur.execute(f"""
                        SELECT product_id, sku, name, rimi_url, category_id,
                               quantity_value, quantity_unit, name_norm
                        FROM products 
                        WHERE category_id IN ({placeholders})
                        ORDER BY name;
                    """, category_ids)
                
                products = cur.fetchall()
                return products
                
        except Exception as e:
            print(f"Error getting products for category: {str(e)}")
            return []
        finally:
            if 'conn' in locals():
                conn.close()

if __name__ == "__main__":
    def test_callback(msg):
        print(f"[{time.strftime('%H:%M:%S')}] {msg}")
    
    # Test the parser
    parser = RimiParser(test_callback)
    db = DatabaseConnection()
    
    category_code = "SH-12"
    category_url = parser.build_category_url(category_code)
    
    # Test pagination parsing
    total_products, total_pages = parser.get_total_products_from_pagination(category_url)
    print(f"Category {category_code}: {total_products} products, {total_pages} pages")
    
    # Test product extraction
    page_url = f"{category_url}?pageSize=20&currentPage=1"
    products = parser.extract_products_from_page(page_url)
    print(f"Extracted {len(products)} products from first page")
    
    # Test hierarchical database connection
    subcategories = db.get_subcategories(category_code)
    print(f"Found {len(subcategories)} subcategories for {category_code}")
    
    db_products = db.get_products_for_category(category_code)
    print(f"Found {len(db_products)} products in database for {category_code}")