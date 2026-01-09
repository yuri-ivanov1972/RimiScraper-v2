#!/usr/bin/env python3
"""
Ingredient Processor - Handles ingredient analysis for new products only
Maintains ingredient frequency tracking and product-ingredient mapping
"""
import os
import time
import psycopg2
import psycopg2.extras
import psycopg2.pool
import re
from typing import Dict, List, Set, Tuple
from datetime import datetime, timezone

class IngredientProcessor:
    """Processes ingredients for new products and maintains frequency tracking"""
    
    def __init__(self, status_callback=None):
        from database_config import db_config
        self.status_callback = status_callback or (lambda x: None)
        self.db_url = db_config.products_db_url
        
        # Create a thread-safe connection pool instead of single connection
        self.connection_pool = None
        self._init_connection_pool()
        
        # Create a shared deduplicator instance that uses the same connection pool
        self.deduplicator = None
        self._init_deduplicator()
    
    def _init_connection_pool(self):
        """Initialize thread-safe connection pool"""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                # Create a connection pool with min 1 connection, max 10 connections  
                # Note: cursor_factory must be set on individual connections
                self.connection_pool = psycopg2.pool.ThreadedConnectionPool(
                    1, 10,  # min and max connections
                    self.db_url
                )
                self.status_callback("Ingredient processor initialized thread-safe connection pool")
                return
            except Exception as e:
                if attempt < max_retries - 1:
                    self.status_callback(f"Connection pool init attempt {attempt + 1} failed, retrying...")
                    time.sleep(1)
                else:
                    raise Exception(f"Connection pool initialization failed after {max_retries} attempts: {str(e)}")

    def _get_connection(self):
        """Get a connection from the thread-safe pool with proper cursor factory"""
        if not self.connection_pool:
            raise Exception("Connection pool not initialized")
        conn = self.connection_pool.getconn()
        # Set cursor factory on the connection for dict-like row access
        conn.cursor_factory = psycopg2.extras.RealDictCursor
        # Keep default autocommit=False to not affect other pool users
        return conn
    
    def _init_deduplicator(self):
        """Initialize shared deduplicator instance with connection pool"""
        try:
            from ingredient_deduplicator import IngredientDeduplicator
            # Pass our connection pool to the deduplicator
            self.deduplicator = IngredientDeduplicator(
                status_callback=self.status_callback,
                connection_pool=self.connection_pool
            )
        except Exception as e:
            self.status_callback(f"Failed to initialize deduplicator: {str(e)}")
            self.deduplicator = None
    
    def _execute_query(self, query: str, params: Tuple = None, fetch: bool = False):
        """Execute query with thread-safe connection handling and proper transaction management"""
        conn = None
        max_retries = 3
        
        # Determine if this is a write operation
        is_write = any(query.strip().upper().startswith(cmd) for cmd in ['INSERT', 'UPDATE', 'DELETE'])
        
        for attempt in range(max_retries):
            try:
                # Get connection from pool
                conn = self._get_connection()
                result = None
                
                # Execute query with proper cursor lifecycle
                with conn.cursor() as cursor:
                    cursor.execute(query, params)
                    if fetch:
                        result = cursor.fetchall()
                    
                    # Commit write operations
                    if is_write and not conn.autocommit:
                        conn.commit()
                
                # Return connection after cursor is closed and committed
                self.connection_pool.putconn(conn)
                return result
                        
            except (psycopg2.OperationalError, psycopg2.InterfaceError) as e:
                if conn:
                    self.connection_pool.putconn(conn, close=True)  # Close bad connection
                    conn = None
                if attempt < max_retries - 1:
                    self.status_callback(f"Query attempt {attempt + 1} failed due to connection issue, retrying...")
                    time.sleep(0.5)
                else:
                    raise Exception(f"Query execution failed after {max_retries} attempts: {str(e)}")
            except Exception as e:
                if conn:
                    try:
                        if is_write and not conn.autocommit:
                            conn.rollback()  # Rollback on error
                        self.connection_pool.putconn(conn, close=True)  # Close on error
                    except:
                        pass
                raise Exception(f"Query execution failed: {str(e)}")
    
    def process_product_ingredients(self, sku: str, ingredients_text: str) -> Dict:
        """
        Process ingredients for a new product (now using autocommit for simplicity)
        
        Args:
            sku: Product SKU
            ingredients_text: Raw ingredients text
            
        Returns:
            Dictionary with processing results
        """
        try:
            if not ingredients_text or ingredients_text.strip() == '':
                self.status_callback(f"No ingredients text for product {sku}")
                return {'processed': 0, 'new_ingredients': 0}
            
            # Extract and normalize ingredients
            ingredients = self._extract_ingredients(ingredients_text)
            
            if not ingredients:
                self.status_callback(f"No ingredients extracted from text for product {sku}")
                return {'processed': 0, 'new_ingredients': 0}
            
            # Process each ingredient (each _execute_query will auto-commit)
            processed_count = 0
            new_ingredients_count = 0
            
            for ingredient in ingredients:
                # Get or create ingredient
                ingredient_id = self._get_or_create_ingredient(ingredient)
                
                if ingredient_id:
                    # Create product-ingredient mapping
                    self._create_ingredient_mapping(ingredient_id, sku)
                    processed_count += 1
                    
                    # Check if this was a new ingredient
                    if self._is_new_ingredient(ingredient_id):
                        new_ingredients_count += 1
            
            self.status_callback(f"Processed {processed_count} ingredients for product {sku} ({new_ingredients_count} new)")
            
            return {
                'processed': processed_count,
                'new_ingredients': new_ingredients_count,
                'ingredients_list': ingredients
            }
            
        except Exception as e:
            raise Exception(f"Failed to process ingredients for {sku}: {str(e)}")
    
    def _extract_ingredients(self, ingredients_text: str) -> List[str]:
        """Extract and normalize individual ingredients from text using tokenization"""
        try:
            # Clean the text
            text = ingredients_text.strip()
            
            # Remove common prefixes (case insensitive)
            text = re.sub(r'^(ingredients?|sastāvs?|sastāvdaļas?)[:;]?\s*', '', text, flags=re.IGNORECASE)
            
            # For single ingredient products (like "olas"), don't split by commas
            if ',' not in text and ';' not in text and ' un ' not in text.lower() and ' and ' not in text.lower():
                # Single ingredient case - but may contain compound ingredients like "vistas OLAS"
                # Check if it contains adjective + noun pattern (common in Latvian)
                words = text.strip().split()
                if len(words) == 2:
                    # For compound ingredients like "vistas OLAS", try to find the main ingredient
                    main_ingredient = words[1].lower()  # "OLAS" -> "olas"
                    normalized_main = self._normalize_ingredient(main_ingredient)
                    if normalized_main and len(normalized_main) > 1:
                        return [normalized_main]
                
                # Use tokenization for single complex ingredients
                tokenized = self._tokenize_ingredient(text.strip())
                if tokenized and len(tokenized) > 1:
                    return [tokenized]
                return []
            
            # Split by common delimiters for multi-ingredient products
            raw_ingredients = re.split(r'[,;]|\band\b|\bun\b', text, flags=re.IGNORECASE)
            
            # Tokenize and normalize each ingredient
            normalized_ingredients = []
            for ingredient in raw_ingredients:
                ingredient = ingredient.strip()
                if ingredient:
                    tokenized = self._tokenize_ingredient(ingredient)
                    if tokenized and len(tokenized) > 1:
                        normalized_ingredients.append(tokenized)
            
            return normalized_ingredients
            
        except Exception as e:
            self.status_callback(f"Error extracting ingredients: {str(e)}")
            return []
    
    def _tokenize_ingredient(self, ingredient_text: str) -> str:
        """Tokenize ingredient text and extract core ingredient from certification info"""
        try:
            if not ingredient_text or not ingredient_text.strip():
                return ""
            
            # Define certification and origin tokens to filter out
            certification_tokens = {
                'lauksaimniecība', 'es', 'eu', 'ārpus', 'organic', 'bio', 
                'bioloģisks', 'bioloģisko', 'bioloģiskās', 'sertificēta',
                'izcelsme', 'valsts', 'valstu', 'kods', 'kodu', 'maisījums',
                'izejvielu', 'izejviela', 'sastāvdaļas', 'sastāvdaļa'
            }
            
            # Define LV-BIO and similar pattern tokens
            bio_pattern = re.compile(r'^[a-z]{2}-bio-\d+$', re.IGNORECASE)
            country_code_pattern = re.compile(r'^[a-z]{2}$', re.IGNORECASE)
            
            # Clean and tokenize
            text = ingredient_text.strip()
            
            # Remove parenthetical information first
            text = re.sub(r'\([^)]*\)', '', text)
            
            # Remove percentages
            text = re.sub(r'\d+%', '', text)
            
            # Split into tokens by spaces and punctuation
            tokens = re.split(r'[\s.,;:]+', text)
            tokens = [token.strip() for token in tokens if token.strip()]
            
            # Filter out certification tokens
            ingredient_tokens = []
            for token in tokens:
                token_lower = token.lower()
                
                # Skip certification tokens
                if token_lower in certification_tokens:
                    continue
                    
                # Skip LV-BIO-XX patterns
                if bio_pattern.match(token):
                    continue
                    
                # Skip standalone country codes (ES, EU, etc.)
                if country_code_pattern.match(token) and len(token) == 2:
                    continue
                    
                # Skip numeric tokens
                if token.isdigit():
                    continue
                    
                # Keep actual ingredient tokens
                ingredient_tokens.append(token_lower)
            
            # Join remaining tokens as the core ingredient
            if ingredient_tokens:
                core_ingredient = ' '.join(ingredient_tokens)
                # Final cleanup
                core_ingredient = core_ingredient.strip('.,;:')
                return core_ingredient
            
            return ""
            
        except Exception as e:
            # Fallback to old normalization method
            return self._normalize_ingredient_fallback(ingredient_text)
    
    def _normalize_ingredient_fallback(self, ingredient: str) -> str:
        """Fallback normalization method (original approach)"""
        try:
            # Remove parenthetical information
            ingredient = re.sub(r'\([^)]*\)', '', ingredient)
            
            # Remove percentages
            ingredient = re.sub(r'\d+%', '', ingredient)
            
            # Remove certification and origin information (case insensitive)
            ingredient = re.sub(r'\.\s*(lauksaimniecība\s+es|lv-bio-\d+|es|eu|organic|bio).*', '', ingredient, flags=re.IGNORECASE)
            ingredient = re.sub(r'\s+(lauksaimniecība\s+es|lv-bio-\d+|es|eu|organic|bio).*', '', ingredient, flags=re.IGNORECASE)
            
            # Remove extra whitespace
            ingredient = re.sub(r'\s+', ' ', ingredient).strip()
            
            # Remove leading/trailing punctuation
            ingredient = ingredient.strip('.,;:')
            
            # Convert to lowercase for consistent matching
            return ingredient.lower()
            
        except Exception as e:
            return ingredient.lower().strip()
    
    def _normalize_ingredient(self, ingredient: str) -> str:
        """Normalize a single ingredient"""
        try:
            # Remove parenthetical information
            ingredient = re.sub(r'\([^)]*\)', '', ingredient)
            
            # Remove percentages
            ingredient = re.sub(r'\d+%', '', ingredient)
            
            # Remove certification and origin information (case insensitive)
            # Common patterns: "Lauksaimniecība ES", "LV-BIO-02", etc.
            ingredient = re.sub(r'\.\s*(lauksaimniecība\s+es|lv-bio-\d+|es|eu|organic|bio).*', '', ingredient, flags=re.IGNORECASE)
            ingredient = re.sub(r'\s+(lauksaimniecība\s+es|lv-bio-\d+|es|eu|organic|bio).*', '', ingredient, flags=re.IGNORECASE)
            
            # Remove extra whitespace
            ingredient = re.sub(r'\s+', ' ', ingredient).strip()
            
            # Remove leading/trailing punctuation
            ingredient = ingredient.strip('.,;:')
            
            # Convert to lowercase for consistent matching
            return ingredient.lower()
            
        except Exception as e:
            return ingredient
    
    def _get_or_create_ingredient(self, ingredient_name: str) -> int:
        """Get existing ingredient ID or create new one with robust handling"""
        # Normalize ingredient name first
        normalized_name = self._normalize_ingredient(ingredient_name)
        if not normalized_name:
            return None
        
        # Use the shared deduplicator to check for existing similar ingredients
        existing_id = None
        if self.deduplicator:
            existing_id = self.deduplicator.find_ingredient_by_similarity(normalized_name)
        
        if existing_id:
            # Update frequency of existing ingredient
            try:
                update_query = "UPDATE ingredient_analysis SET frequency = frequency + 1 WHERE id = %s"
                self._execute_query(update_query, (existing_id,))
                return existing_id
            except:
                return existing_id  # Return ID even if frequency update fails
            
        max_retries = 3
        
        for attempt in range(max_retries):
            try:
                # Double-check with exact case-insensitive search
                select_query = "SELECT id FROM ingredient_analysis WHERE LOWER(ingredient) = LOWER(%s)"
                result = self._execute_query(select_query, (normalized_name,), fetch=True)
                
                if result and len(result) > 0:
                    # Ingredient exists, update frequency
                    ingredient_id = result[0]['id']
                    try:
                        update_query = "UPDATE ingredient_analysis SET frequency = frequency + 1 WHERE id = %s"
                        self._execute_query(update_query, (ingredient_id,))
                    except:
                        pass  # Frequency update failure is not critical
                    return ingredient_id
                
                # Ingredient doesn't exist, create it atomically (race-safe)
                try:
                    # Use atomic insert with sequence default - no race conditions
                    insert_query = """
                        INSERT INTO ingredient_analysis (ingredient, frequency) 
                        VALUES (%s, 1)
                        ON CONFLICT (ingredient) DO UPDATE SET 
                            frequency = ingredient_analysis.frequency + 1
                        RETURNING id
                    """
                    insert_result = self._execute_query(insert_query, (normalized_name,), fetch=True)
                    if insert_result and len(insert_result) > 0:
                        new_id = insert_result[0]['id']
                        self._auto_create_uncategorized_canonical(new_id, normalized_name)
                        return new_id
                
                except Exception as insert_error:
                    # If insert fails, try one more time to get existing
                    retry_result = self._execute_query(select_query, (normalized_name,), fetch=True)
                    if retry_result and len(retry_result) > 0:
                        return retry_result[0]['id']
                    
                    if attempt == max_retries - 1:  # Last attempt
                        self.status_callback(f"Failed to create ingredient after {max_retries} attempts: {ingredient_name}")
                        return None
                
            except Exception as e:
                if attempt == max_retries - 1:  # Last attempt
                    self.status_callback(f"Error processing ingredient {ingredient_name}: {str(e)}")
                    return None
                
                # Short delay before retry
                import time
                time.sleep(0.1)
        
        return None
    
    def _auto_create_uncategorized_canonical(self, ingredient_id: int, ingredient_name: str):
        """Auto-create uncategorized canonical entry for new ingredients not yet mapped"""
        try:
            check_query = "SELECT 1 FROM ingredient_mapping WHERE ingredient_id = %s"
            result = self._execute_query(check_query, (ingredient_id,), fetch=True)
            
            if result and len(result) > 0:
                return
            
            canonical_insert = """
                INSERT INTO ingredient_canonical (canonical_id, name, type, description)
                VALUES (%s, %s, 'uncategorized', 'Auto-created - needs categorization')
                ON CONFLICT (canonical_id) DO NOTHING
            """
            self._execute_query(canonical_insert, (ingredient_id, ingredient_name))
            
            mapping_insert = """
                INSERT INTO ingredient_mapping (ingredient_id, canonical_id)
                VALUES (%s, %s)
                ON CONFLICT (ingredient_id) DO NOTHING
            """
            self._execute_query(mapping_insert, (ingredient_id, ingredient_id))
            
        except Exception as e:
            self.status_callback(f"Warning: Could not auto-create canonical for {ingredient_name}: {str(e)}")

    def _create_ingredient_mapping(self, ingredient_id: int, sku: str):
        """Create product-ingredient mapping"""
        try:
            mapping_query = """
                INSERT INTO ingredient_product_mapping (ingredient_id, product_sku)
                VALUES (%s, %s)
                ON CONFLICT (ingredient_id, product_sku) DO NOTHING
            """
            self._execute_query(mapping_query, (ingredient_id, sku))
            
        except Exception as e:
            self.status_callback(f"Error creating ingredient mapping: {str(e)}")
    
    def _is_new_ingredient(self, ingredient_id: int) -> bool:
        """Check if ingredient was just created (frequency = 1)"""
        try:
            check_query = "SELECT frequency FROM ingredient_analysis WHERE id = %s"
            result = self._execute_query(check_query, (ingredient_id,), fetch=True)
            return result and result[0]['frequency'] == 1
        except:
            return False
    
    def get_ingredient_statistics(self) -> Dict:
        """Get ingredient processing statistics"""
        try:
            stats = {}
            
            # Total unique ingredients
            total_query = "SELECT COUNT(*) as count FROM ingredient_analysis"
            result = self._execute_query(total_query, fetch=True)
            stats['total_ingredients'] = result[0]['count']
            
            # Most common ingredients
            common_query = """
                SELECT ingredient, frequency 
                FROM ingredient_analysis 
                ORDER BY frequency DESC 
                LIMIT 10
            """
            result = self._execute_query(common_query, fetch=True)
            stats['most_common'] = [dict(row) for row in result] if result else []
            
            # Recent ingredient additions
            recent_query = """
                SELECT COUNT(*) as count 
                FROM ingredient_analysis 
                WHERE created_at > NOW() - INTERVAL '24 hours'
            """
            result = self._execute_query(recent_query, fetch=True)
            stats['recent_additions'] = result[0]['count']
            
            return stats
            
        except Exception as e:
            self.status_callback(f"Error getting ingredient statistics: {str(e)}")
            return {}
    
    def close(self):
        """Clean up database connections and resources"""
        try:
            # Close deduplicator first
            if self.deduplicator:
                self.deduplicator.close()
                self.deduplicator = None
            
            # Close connection pool (check if not already closed)
            if self.connection_pool and not self.connection_pool.closed:
                self.connection_pool.closeall()
                self.status_callback("Ingredient processor connection pool closed")
            elif self.connection_pool and self.connection_pool.closed:
                self.status_callback("Ingredient processor connection pool already closed")
        except Exception as e:
            self.status_callback(f"Error closing connections: {str(e)}")