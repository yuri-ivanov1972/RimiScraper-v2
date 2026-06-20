#!/usr/bin/env python3
"""
Batch Processor - Optimized batch processing for multiple products
Includes connection pooling, progress tracking, error recovery, and smart updates
"""
import os
import time
import threading
from typing import Dict, List, Optional, Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from update_coordinator import UpdateCoordinator
from smart_updater import SmartUpdater, UpdateStatisticsCollector

class BatchProcessor:
    """Handles batch processing of products with robust connection management"""
    
    def __init__(self, status_callback=None, max_workers=3, heartbeat_callback=None):
        self.status_callback = status_callback or (lambda x: None)
        self.heartbeat_callback = heartbeat_callback or (lambda: None)
        self.max_workers = max_workers
        # Thread-local storage for coordinators by type to enable reuse per thread
        self._thread_coordinators = {}  # {thread_id: {"regular": coord, "enhanced": coord}}
        self._all_coordinators = []  # Track all coordinators for cleanup
        self._lock = threading.Lock()
        
    def _get_coordinator(self, enhanced: bool = False) -> UpdateCoordinator:
        """Get or create a coordinator for the current thread - reuse per thread and type"""
        thread_id = threading.current_thread().ident
        coord_type = "enhanced" if enhanced else "regular"
        
        with self._lock:
            # Initialize thread coordinators dict if needed
            if thread_id not in self._thread_coordinators:
                self._thread_coordinators[thread_id] = {}
            
            # Check if we already have coordinator of this type for this thread
            if coord_type in self._thread_coordinators[thread_id]:
                return self._thread_coordinators[thread_id][coord_type]
            
            # Create thread-safe callback that doesn't rely on Streamlit context
            def thread_safe_callback(msg):
                print(f"[COORDINATOR] {msg}")
            
            # Create coordinator based on type needed
            if enhanced:
                from enhanced_update_coordinator import EnhancedUpdateCoordinator
                coordinator = EnhancedUpdateCoordinator(thread_safe_callback)
            else:
                coordinator = UpdateCoordinator(thread_safe_callback)
            
            # Store coordinator for reuse by this thread and type
            self._thread_coordinators[thread_id][coord_type] = coordinator
            self._all_coordinators.append(coordinator)
            
            print(f"🔧 BATCH: Created reusable {coord_type} coordinator for thread {thread_id}")
            return coordinator
    
    def process_product_batch(self, products: List[Dict], category_code: Optional[str] = None, force_update: bool = False, fallback_category_code: Optional[str] = None) -> Dict:
        """
        Process a batch of products with optimized connection handling
        
        Args:
            products: List of product dictionaries with 'sku' and optionally 'name'
            category_code: Default category code to use (if set, skips auto-extraction)
            force_update: Whether to force update existing products (default: False)
            fallback_category_code: Category code to use if auto-extracted category doesn't exist in DB
            
        Returns:
            Dictionary with batch processing results
        """
        start_time = time.time()
        results = {
            'total_products': len(products),
            'successful': 0,
            'failed': 0,
            'errors': [],
            'processing_time': 0,
            'products_processed': []
        }
        
        self.status_callback(f"Starting batch processing of {len(products)} products")
        
        def process_single_product(product_info):
            """Process a single product in a thread-safe manner"""
            sku = product_info.get('sku') or str(product_info)
            coordinator = None
            
            # Create thread-safe callback that updates both logs and Streamlit UI
            def thread_safe_callback(msg):
                # Print to logs for debugging
                print(f"[THREAD-{sku}] {msg}")
                # Also update Streamlit UI with progress
                try:
                    self.status_callback(f"[{sku}] {msg}")
                except Exception as ui_error:
                    # Fallback to console if UI update fails
                    print(f"[THREAD-{sku}] UI update failed: {ui_error}")
            
            try:
                print(f"🚀 BATCH: Starting thread processing for {sku}")
                
                print(f"🔄 BATCH: Processing product {sku}")
                
                # Use automatic category extraction if no category_code provided
                if category_code is None:
                    print(f"🔄 BATCH: Using automatic category extraction for {sku}")
                    if fallback_category_code:
                        print(f"🔄 BATCH: Fallback category if extraction fails: {fallback_category_code}")
                    print(f"🔄 BATCH: Thread ID: {threading.current_thread().ident}")
                    print(f"🔄 BATCH: Thread name: {threading.current_thread().name}")
                    
                    try:
                        # Get/reuse enhanced coordinator for this thread
                        print(f"🔄 BATCH: Getting reusable enhanced coordinator...")
                        enhanced_coordinator = self._get_coordinator(enhanced=True)
                        
                        print(f"🔄 BATCH: Calling process_single_product_with_auto_category (force_update={force_update})...")
                        result = enhanced_coordinator.process_single_product_with_auto_category(sku, force_update=force_update, fallback_category_code=fallback_category_code)
                        
                        print(f"🔄 BATCH: Processing completed, result type: {type(result)}")
                        print(f"🔄 BATCH: Result success: {getattr(result, 'success', 'N/A')}")
                        if hasattr(result, 'errors') and result.errors:
                            print(f"🔄 BATCH: Result errors: {result.errors}")
                        
                        # NOTE: Don't close coordinator here - reuse for other products!
                        print(f"🔄 BATCH: Coordinator reused successfully (not closing)")
                        
                    except Exception as batch_error:
                        print(f"❌ BATCH: Exception during auto category processing: {str(batch_error)}")
                        import traceback
                        print(f"❌ BATCH: Traceback: {traceback.format_exc()}")
                        raise batch_error
                else:
                    print(f"🔄 BATCH: Using manual category {category_code} for {sku} (force_update={force_update})")
                    # Get/reuse regular coordinator for this thread
                    coordinator = self._get_coordinator(enhanced=False)
                    result = coordinator.process_single_product(sku, category_code, force_update=force_update)
                
                print(f"🔍 BATCH: Checking result for {sku}...")
                success = result['success'] if isinstance(result, dict) else result.success
                print(f"🔍 BATCH: Success status for {sku}: {success}")
                
                if success:
                    print(f"✅ BATCH: {sku} processed successfully")
                    return {'sku': sku, 'status': 'success', 'result': result}
                else:
                    if isinstance(result, dict):
                        error_msg = result.get('error', 'Unknown error')
                        errors = result.get('errors', [])
                    else:
                        error_msg = 'Processing failed'
                        errors = getattr(result, 'errors', [])
                    
                    print(f"❌ BATCH: {sku} failed with error: {error_msg}")
                    if errors:
                        print(f"❌ BATCH: {sku} detailed errors: {errors}")
                    return {'sku': sku, 'status': 'failed', 'error': error_msg}
                    
            except Exception as e:
                error_msg = f"Exception processing {sku}: {str(e)}"
                self.status_callback(error_msg)
                return {'sku': sku, 'status': 'failed', 'error': error_msg}
            
            finally:
                # NOTE: Don't close coordinators here anymore - they are reused per thread
                # Coordinators will be closed when the entire batch is done
                pass
        
        # Process products with thread pool
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_product = {
                executor.submit(process_single_product, product): product 
                for product in products
            }
            
            for future in as_completed(future_to_product):
                try:
                    result = future.result()
                    results['products_processed'].append(result)
                    
                    if result['status'] == 'success':
                        results['successful'] += 1
                        self.status_callback(f"✓ {result['sku']} processed successfully")
                    else:
                        results['failed'] += 1
                        results['errors'].append(result['error'])
                        self.status_callback(f"✗ {result['sku']} failed: {result['error']}")
                    
                    # Send heartbeat after each product to prevent long gaps
                    # This ensures maximum granularity and eliminates stuck job false positives
                    try:
                        self.heartbeat_callback()
                    except Exception as hb_error:
                        print(f"⚠️ Heartbeat callback error: {hb_error}")
                        
                except Exception as e:
                    results['failed'] += 1
                    error_msg = f"Future execution error: {str(e)}"
                    results['errors'].append(error_msg)
                    self.status_callback(error_msg)
        
        results['processing_time'] = time.time() - start_time
        
        # Close reused coordinators after batch completion
        try:
            self.close()
        except Exception as e:
            print(f"⚠️ BATCH: Error closing coordinators: {e}")
        
        self.status_callback(f"Batch processing completed: {results['successful']} successful, {results['failed']} failed")
        return results
    
    def process_sku_list(self, sku_list: List[str], category_code: str = 'SH-1-1-1', force_update: bool = False) -> Dict:
        """
        Process a list of SKUs
        
        Args:
            sku_list: List of product SKUs
            category_code: Category code to use for all products
            force_update: Whether to force update existing products (default: False)
            
        Returns:
            Batch processing results
        """
        products = [{'sku': sku} for sku in sku_list]
        return self.process_product_batch(products, category_code, force_update=force_update)
    
    def process_sku_list_with_auto_category(self, sku_list: List[str], force_update: bool = False) -> Dict:
        """
        Process a list of SKUs with automatic category extraction
        
        Args:
            sku_list: List of product SKUs
            force_update: Whether to force update existing products (default: False)
            
        Returns:
            Batch processing results
        """
        products = [{'sku': sku} for sku in sku_list]
        return self.process_product_batch(products, None, force_update=force_update)  # None triggers auto-extraction
    
    def process_sku_list_chunked(self, job_id: int, chunk_size: int = 15, force_update: bool = False, smart_mode: bool = False, update_mode: str = 'full') -> Dict:
        """
        Process SKUs in chunks with progress tracking for large batches
        
        Args:
            job_id: Processing job ID for progress tracking
            chunk_size: Number of products to process in each chunk (default: 15)
            force_update: Whether to force update existing products
            smart_mode: Enable smart updates (only update changed fields, skip photos)
            update_mode: Update mode - 'full' (complete re-scrape) or 'incremental' (new products + price/availability)
            
        Returns:
            Batch processing results with chunk progress
        """
        from progress_manager import ProgressManager
        
        start_time = time.time()
        total_results = {
            'total_products': 0,
            'successful': 0,
            'failed': 0,
            'errors': [],
            'processing_time': 0,
            'chunks_processed': 0,
            'interrupted': False,
            'new_products': 0,  # Track new products in incremental mode
            'updated_products': 0  # Track updated existing products
        }
        
        progress_mgr = ProgressManager(self.status_callback)
        
        # Always get category code from job for fallback when auto-extraction fails
        import psycopg2
        db_url = os.environ['DATABASE_URL']
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
        cur.execute("SELECT category_code FROM category_processing_jobs WHERE id = %s", (job_id,))
        job_category_row = cur.fetchone()
        job_category_code = job_category_row[0] if job_category_row else None
        conn.close()
        
        if job_category_code:
            self.status_callback(f"📌 Job category: {job_category_code} (fallback for invalid extracted categories)")
        
        # Initialize smart updater and statistics collector if in smart mode
        stats_collector = None
        if smart_mode:
            stats_collector = UpdateStatisticsCollector(db_url, job_id, job_category_code)
            self.status_callback(f"🎯 Smart mode enabled: will update only changed fields")
        
        try:
            # Get all pending SKUs for this job
            pending_skus = progress_mgr.get_pending_skus(job_id)
            
            if not pending_skus:
                self.status_callback("✓ No pending SKUs to process")
                return total_results
            
            total_results['total_products'] = len(pending_skus)
            
            # INCREMENTAL MODE: Classify SKUs and use lightweight updates for existing products
            new_skus = pending_skus  # Default: treat all as new (full scrape)
            existing_skus_data = {}  # SKU -> listing data mapping
            
            if update_mode == 'incremental':
                self.status_callback(f"🔄 Incremental mode: classifying {len(pending_skus)} SKUs...")
                
                from sku_classifier import SkuClassifier
                from lightweight_updater import LightweightUpdater
                from core_parser import RimiParser
                
                # Classify SKUs using already-fetched job category
                classifier = SkuClassifier()
                classification = classifier.classify_skus(job_category_code, pending_skus)
                
                new_skus = classification['new']
                existing_skus = classification['existing']
                existing_skus_set = set(existing_skus)  # For efficient lookup
                removed_skus = classification['removed']
                
                self.status_callback(f"  ✨ New products: {len(new_skus)} (will do full scrape)")
                self.status_callback(f"  🔄 Existing products: {len(existing_skus)} (price update from listing)")
                self.status_callback(f"  ❌ Removed products: {len(removed_skus)} (mark inactive)")
                
                # Mark removed products as inactive
                if removed_skus:
                    removed_count = classifier.mark_products_inactive(removed_skus, job_category_code)
                    self.status_callback(f"  ✓ Marked {removed_count} products as inactive")
                    total_results['removed_products'] = removed_count
                
                # For existing products: update prices from category listing pages
                if existing_skus:
                    # Guard: job_category_code required for price scraping
                    if not job_category_code:
                        self.status_callback(f"  ⚠️  No category code - skipping price updates for {len(existing_skus)} existing products")
                        for sku in existing_skus:
                            progress_mgr.update_product_status(job_id, sku, 'completed')
                        total_results['successful'] += len(existing_skus)
                    else:
                        self.status_callback(f"  💰 Updating prices for {len(existing_skus)} existing products from listing...")
                        
                        # Collect products with prices from category pages (with error handling)
                        try:
                            parser = RimiParser(self.status_callback)
                            category_products = parser.collect_category_products(job_category_code)
                        except Exception as e:
                            self.status_callback(f"  ⚠️  Failed to scrape category: {e} - skipping price updates")
                            category_products = []
                        
                        # Build price lookup from category page data
                        # Include unavailable products too (they have is_available=False)
                        listing_data = {}
                        for product in category_products:
                            if product.sku in existing_skus_set:
                                # Include product if it has a price OR is marked as unavailable
                                if product.price or not product.is_available:
                                    listing_data[product.sku] = {
                                        'price': product.price,
                                        'name': product.name,
                                        'price_per_unit': product.price_per_unit,
                                        'price_per_unit_type': product.price_per_unit_type,
                                        'discount_price': product.discount_price,
                                        'discount_price_per_unit': product.discount_price_per_unit,
                                        'is_available': product.is_available
                                    }
                        
                        self.status_callback(f"  📊 Found prices for {len(listing_data)}/{len(existing_skus)} existing products")

                        # Sanity check: if every product in the listing came back as unavailable,
                        # this is almost certainly a scraping failure (geo-block, bot detection, etc.)
                        # rather than a genuine full-category stock-out. Skip availability updates
                        # to avoid overwriting good data with bad scrape results.
                        all_unavailable = (
                            len(listing_data) > 0 and
                            all(not v['is_available'] for v in listing_data.values())
                        )
                        if all_unavailable:
                            self.status_callback(
                                f"  ⚠️  All {len(listing_data)} products returned as unavailable — "
                                f"possible geo-block or scrape failure. Skipping availability update."
                            )
                            listing_data = {}

                        # Batch update prices using lightweight updater
                        successful_skus = set()
                        failed_skus = set()

                        if listing_data:
                            updater = LightweightUpdater()
                            update_results = updater.batch_update_from_listing(listing_data)
                            
                            self.status_callback(f"  ✓ Price updates: {update_results['successful']} successful, {update_results['failed']} failed")
                            self.status_callback(f"  📈 Price changes detected: {update_results['price_changes']}")
                            
                            # Track successful and failed SKUs from update results
                            for error_info in update_results.get('errors', []):
                                failed_sku = error_info.get('sku')
                                if failed_sku:
                                    failed_skus.add(failed_sku)
                                    total_results['errors'].append(f"SKU {failed_sku}: {error_info.get('error', 'Unknown error')}")
                            
                            successful_skus = set(listing_data.keys()) - failed_skus
                            
                            # Mark products based on actual update status
                            for sku in successful_skus:
                                progress_mgr.update_product_status(job_id, sku, 'completed')
                            for sku in failed_skus:
                                progress_mgr.update_product_status(job_id, sku, 'failed', 'Lightweight update failed')
                            
                            total_results['successful'] += len(successful_skus)
                            total_results['failed'] += len(failed_skus)
                            total_results['price_changes'] = update_results.get('price_changes', 0)
                        
                        # Handle products not found in listing (mark completed, no price update)
                        skus_without_prices = existing_skus_set - set(listing_data.keys())
                        if skus_without_prices:
                            self.status_callback(f"  ⚠️  {len(skus_without_prices)} products not found in listing (no price update)")
                            for sku in skus_without_prices:
                                progress_mgr.update_product_status(job_id, sku, 'completed')
                            total_results['successful'] += len(skus_without_prices)
                
                total_results['new_products'] = len(new_skus)
                total_results['updated_products'] = len(existing_skus)
                
                # Update pending_skus to only include new products
                pending_skus = new_skus
            
            if not pending_skus:
                self.status_callback("✓ No new products to scrape (all existing)")
                # CRITICAL: Must complete job even when no new products to scrape
                progress_mgr.update_job_progress(job_id)
                progress_mgr.complete_job(job_id)
                total_results['processing_time'] = time.time() - start_time
                return total_results
            
            self.status_callback(f"📦 Processing {len(pending_skus)} NEW products in chunks of {chunk_size}")
            
            # Process in chunks (only new products in incremental mode)
            for chunk_num, i in enumerate(range(0, len(pending_skus), chunk_size), 1):
                chunk_skus = pending_skus[i:i + chunk_size]
                chunk_start = time.time()
                
                self.status_callback(f"\n🔄 Chunk {chunk_num}: Processing {len(chunk_skus)} products (SKUs {i+1}-{min(i+chunk_size, len(pending_skus))})")
                
                # Mark all products in chunk as 'processing'
                for sku in chunk_skus:
                    progress_mgr.update_product_status(job_id, sku, 'processing')
                
                # Process chunk with job category as fallback for invalid extracted categories
                products = [{'sku': sku} for sku in chunk_skus]
                chunk_results = self.process_product_batch(products, None, force_update=force_update, fallback_category_code=job_category_code)
                
                # Update individual product statuses based on results
                for product_result in chunk_results['products_processed']:
                    sku = product_result['sku']
                    if product_result['status'] == 'success':
                        progress_mgr.update_product_status(job_id, sku, 'completed')
                    else:
                        error_msg = product_result.get('error', 'Unknown error')
                        progress_mgr.update_product_status(job_id, sku, 'failed', error_msg)
                
                # Update job progress
                progress_mgr.update_job_progress(job_id)
                
                # Accumulate results
                total_results['successful'] += chunk_results['successful']
                total_results['failed'] += chunk_results['failed']
                total_results['errors'].extend(chunk_results['errors'])
                total_results['chunks_processed'] += 1
                
                chunk_time = time.time() - chunk_start
                self.status_callback(f"✓ Chunk {chunk_num} completed in {chunk_time:.1f}s ({chunk_results['successful']}/{len(chunk_skus)} successful)")
                
                # Brief pause between chunks to avoid overwhelming the system
                if i + chunk_size < len(pending_skus):
                    time.sleep(0.5)
            
            # Mark job as completed
            progress_mgr.complete_job(job_id)
            self.status_callback(f"✅ All chunks processed successfully!")
            
            # Save statistics if in smart mode
            if stats_collector:
                stats_collector.save_to_database()
                self.status_callback(f"\n📊 {stats_collector.get_summary()}")
            
        except KeyboardInterrupt:
            self.status_callback("⚠️ Processing interrupted by user - progress saved")
            total_results['interrupted'] = True
            progress_mgr.update_job_progress(job_id)
            
            # Save partial statistics if in smart mode
            if stats_collector:
                try:
                    stats_collector.save_to_database()
                except Exception as e:
                    self.status_callback(f"⚠️ Could not save statistics: {e}")
            
            # Re-raise to allow worker.py to handle graceful shutdown
            raise
        except Exception as e:
            self.status_callback(f"❌ Error during chunked processing: {str(e)}")
            total_results['errors'].append(str(e))
            progress_mgr.update_job_progress(job_id)
            
            # Save partial statistics if in smart mode
            if stats_collector:
                try:
                    stats_collector.save_to_database()
                except Exception as e:
                    self.status_callback(f"⚠️ Could not save statistics: {e}")
        
        total_results['processing_time'] = time.time() - start_time
        return total_results
    
    def close(self):
        """Close all coordinator connections - now closes reused coordinators"""
        with self._lock:
            closed_count = 0
            for coordinator in self._all_coordinators:
                try:
                    coordinator.close()
                    closed_count += 1
                except:
                    pass
            
            # Clear all coordinator references
            self._thread_coordinators.clear()
            self._all_coordinators.clear()
            
            print(f"🔧 BATCH: Closed {closed_count} reused coordinators")
            self.status_callback(f"Batch processor closed {closed_count} coordinator connections")

def test_batch_processing():
    """Test batch processing functionality"""
    def status_callback(msg):
        print(f'[BATCH] {msg}')
    
    processor = BatchProcessor(status_callback, max_workers=2)
    
    print('=== TESTING BATCH PROCESSING ===')
    
    # Test with a small batch of products
    test_skus = ['147762', '961367', '999409']
    results = processor.process_sku_list(test_skus)
    
    print(f'\nBatch Results:')
    print(f'  Total: {results["total_products"]}')
    print(f'  Successful: {results["successful"]}')
    print(f'  Failed: {results["failed"]}')
    print(f'  Processing time: {results["processing_time"]:.2f}s')
    
    if results['errors']:
        print(f'  Errors: {len(results["errors"])}')
        for error in results['errors'][:3]:  # Show first 3 errors
            print(f'    - {error}')
    
    processor.close()
    return results

if __name__ == "__main__":
    test_batch_processing()