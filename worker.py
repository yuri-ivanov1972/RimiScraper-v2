#!/usr/bin/env python3
"""
Standalone Worker for Category Processing
Runs independently of Streamlit for robust overnight processing
"""
import os
import sys

# CRITICAL: Parse --production flag BEFORE any imports that use DatabaseConfig
# This ensures db_config.is_development returns False when running in production mode
def _early_parse_production_flag():
    """Parse --production flag early to set ENVIRONMENT before other imports"""
    if '--production' in sys.argv:
        os.environ['ENVIRONMENT'] = 'production'
        return True
    return False

_use_production_early = _early_parse_production_flag()

import argparse
import signal
import socket
import time
import logging
import json
import resource
from datetime import datetime
from typing import Optional, List
import psycopg2
from psycopg2.extras import RealDictCursor

from core_parser import RimiParser
from batch_processor import BatchProcessor
from progress_manager import ProgressManager


class ProcessingWorker:
    """Standalone worker for processing categories from job queue"""
    
    def __init__(self, worker_id: str, heartbeat_interval: int = 30, chunk_size: int = 15, max_workers: int = 3, log_dir: str = "logs", use_production: bool = False):
        self.worker_id = worker_id
        self.heartbeat_interval = heartbeat_interval
        self.chunk_size = chunk_size
        self.max_workers = max_workers
        self.log_dir = log_dir
        self.last_heartbeat_time = 0  # Track last heartbeat timestamp for throttling
        self.last_heartbeat_status = None  # Track last status to detect changes
        self.last_heartbeat_job_id = None  # Track last job_id to detect changes
        self.running = True
        self.current_job_id = None
        self.use_production = use_production
        
        # Setup logging
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, f"worker_{worker_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
        
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_file),
                logging.StreamHandler(sys.stdout)
            ]
        )
        self.logger = logging.getLogger(__name__)
        self.logger.info(f"Worker {worker_id} initialized, log file: {log_file}")
        
        # Register signal handlers for graceful shutdown
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)
        
        # Database connection - select based on environment
        if use_production:
            self.db_url = os.environ.get('PROD_DATABASE_URL')
            if not self.db_url:
                raise ValueError("PROD_DATABASE_URL not set, but --production flag was used")
            # CRITICAL: Override DATABASE_URL so all downstream components use production
            os.environ['DATABASE_URL'] = self.db_url
            self.logger.info("=" * 60)
            self.logger.info("🚀 PRODUCTION MODE: Using production database")
            self.logger.info("   DATABASE_URL overridden for all components")
            self.logger.info("=" * 60)
        else:
            self.db_url = os.environ['DATABASE_URL']
            self.logger.info("=" * 60)
            self.logger.info("🔧 DEVELOPMENT MODE: Using development database")
            self.logger.info("=" * 60)
        
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals gracefully"""
        self.logger.info(f"Received signal {signum}, initiating graceful shutdown...")
        self.running = False
        # Raise KeyboardInterrupt to interrupt any long-running operations
        raise KeyboardInterrupt("Shutdown signal received")
        
    def _get_db_connection(self):
        """Get database connection"""
        return psycopg2.connect(self.db_url, cursor_factory=RealDictCursor)
    
    def register_worker(self):
        """Register this worker in the database"""
        conn = None
        try:
            conn = self._get_db_connection()
            cur = conn.cursor()
            
            hostname = socket.gethostname()
            pid = os.getpid()
            
            cur.execute("""
                INSERT INTO processing_workers (worker_id, hostname, pid, status, last_heartbeat)
                VALUES (%s, %s, %s, 'idle', CURRENT_TIMESTAMP)
                ON CONFLICT (worker_id) DO UPDATE
                SET hostname = EXCLUDED.hostname,
                    pid = EXCLUDED.pid,
                    status = 'idle',
                    last_heartbeat = CURRENT_TIMESTAMP,
                    started_at = CURRENT_TIMESTAMP,
                    stopped_at = NULL,
                    error_message = NULL
            """, (self.worker_id, hostname, pid))
            
            conn.commit()
            self.logger.info(f"Worker registered: {self.worker_id} on {hostname} (PID: {pid})")
            
        except Exception as e:
            self.logger.error(f"Failed to register worker: {e}")
            if conn:
                conn.rollback()
            raise
        finally:
            if conn:
                conn.close()
    
    def update_heartbeat(self, status: str = 'processing', job_id: Optional[int] = None, force: bool = False):
        """
        Update worker heartbeat and status with intelligent throttling
        
        Throttles mid-chunk heartbeats to 30s interval to prevent excessive DB writes,
        but always forces updates when status or job_id changes to maintain accuracy.
        
        Args:
            status: Worker status ('processing', 'idle', etc.)
            job_id: Current job ID being processed
            force: If True, bypass throttling and update immediately
        """
        import time
        
        current_time = time.time()
        
        # Check if this is a forced update (explicit parameter or state change)
        if not force:
            # Auto-detect critical state transitions that should force an update
            status_changed = status != self.last_heartbeat_status
            job_changed = job_id != self.last_heartbeat_job_id
            
            if status_changed or job_changed:
                force = True  # Force update on state change
        
        # Throttle heartbeats to prevent excessive database writes
        # Skip update only if not forced AND throttle interval hasn't elapsed
        if not force:
            time_since_last = current_time - self.last_heartbeat_time
            if time_since_last < self.heartbeat_interval:
                return  # Skip update - throttled (not forced, too soon since last heartbeat)
        
        conn = None
        try:
            conn = self._get_db_connection()
            cur = conn.cursor()
            
            cur.execute("""
                UPDATE processing_workers
                SET last_heartbeat = CURRENT_TIMESTAMP,
                    status = %s,
                    current_job_id = %s
                WHERE worker_id = %s
            """, (status, job_id, self.worker_id))
            
            conn.commit()
            
            # Update tracking variables after successful write
            self.last_heartbeat_time = current_time
            self.last_heartbeat_status = status
            self.last_heartbeat_job_id = job_id
            
        except Exception as e:
            self.logger.error(f"Failed to update heartbeat: {e}")
            if conn:
                conn.rollback()
        finally:
            if conn:
                conn.close()
    
    def log_event(self, job_id: int, event_type: str, message: str, metadata: dict = None):
        """Log job event to database"""
        conn = None
        try:
            conn = self._get_db_connection()
            cur = conn.cursor()
            
            cur.execute("""
                INSERT INTO job_events (job_id, event_type, message, metadata)
                VALUES (%s, %s, %s, %s)
            """, (job_id, event_type, message, json.dumps(metadata) if metadata else None))
            
            conn.commit()
            
        except Exception as e:
            self.logger.error(f"Failed to log event: {e}")
            if conn:
                conn.rollback()
        finally:
            if conn:
                conn.close()
    
    def acquire_next_job(self) -> Optional[dict]:
        """Acquire next job from queue using SELECT FOR UPDATE SKIP LOCKED"""
        conn = None
        try:
            conn = self._get_db_connection()
            cur = conn.cursor()
            
            # Heartbeat stale threshold: 2x heartbeat interval
            stale_threshold_seconds = self.heartbeat_interval * 2
            
            # Find next job ordered by priority (higher first) and scheduled time
            # Only select:
            # 1. 'queued' jobs, OR
            # 2. 'in_progress' jobs with stale heartbeat (worker died)
            cur.execute("""
                SELECT id, category_code, category_id, total_products, processed_count,
                       priority, scheduled_for, retry_count, max_retries, current_worker_id,
                       update_mode
                FROM category_processing_jobs
                WHERE (
                    (status = 'queued') OR
                    (status = 'in_progress' AND (
                        last_heartbeat IS NULL OR
                        last_heartbeat < CURRENT_TIMESTAMP - INTERVAL '%s seconds'
                    ))
                  )
                  AND scheduled_for <= CURRENT_TIMESTAMP
                  AND retry_count < max_retries
                ORDER BY priority DESC, scheduled_for ASC
                LIMIT 1
                FOR UPDATE SKIP LOCKED
            """, (stale_threshold_seconds,))
            
            job = cur.fetchone()
            
            if job:
                # Check if this is a reassignment of stale job
                was_stale = job['current_worker_id'] is not None
                
                # Lock the job for this worker
                cur.execute("""
                    UPDATE category_processing_jobs
                    SET status = 'in_progress',
                        current_worker_id = %s,
                        last_heartbeat = CURRENT_TIMESTAMP,
                        lock_version = lock_version + 1
                    WHERE id = %s
                    RETURNING *
                """, (self.worker_id, job['id']))
                
                locked_job = cur.fetchone()
                conn.commit()
                
                if was_stale:
                    self.logger.warning(f"Acquired stale job #{locked_job['id']} (previous worker: {job['current_worker_id']})")
                    self.log_event(locked_job['id'], 'job_reassigned', f"Reassigned from stale worker {job['current_worker_id']} to {self.worker_id}")
                else:
                    self.logger.info(f"Acquired job #{locked_job['id']}: {locked_job['category_code']} (priority: {locked_job['priority']})")
                
                return dict(locked_job)
            
            return None
            
        except Exception as e:
            self.logger.error(f"Failed to acquire job: {e}")
            if conn:
                conn.rollback()
            return None
        finally:
            if conn:
                conn.close()
    
    def _get_memory_usage_mb(self) -> float:
        """Get current memory usage in MB"""
        usage = resource.getrusage(resource.RUSAGE_SELF)
        return usage.ru_maxrss / 1024  # Convert KB to MB
    
    def process_job(self, job: dict):
        """Process a single job"""
        job_id = job['id']
        category_code = job['category_code']
        update_mode = job.get('update_mode', 'full')  # Default to 'full' for backward compatibility
        
        self.current_job_id = job_id
        self.log_event(job_id, 'job_started', f"Worker {self.worker_id} started processing {category_code} (mode: {update_mode})")
        
        # Log initial memory usage
        initial_memory = self._get_memory_usage_mb()
        self.logger.info(f"💾 Initial memory usage: {initial_memory:.1f} MB")
        
        try:
            self.logger.info(f"Processing job #{job_id}: {category_code}")
            
            # If this is a resumed job, reset stale processing records
            progress_mgr = ProgressManager(lambda msg: self.logger.info(msg))
            
            if job['processed_count'] > 0:
                self.logger.info(f"Resuming job with {job['processed_count']}/{job['total_products']} already processed")
                reset_count = progress_mgr.reset_stale_processing_records(job_id)
                if reset_count > 0:
                    self.log_event(job_id, 'interrupted_skus_reset', f"Reset {reset_count} interrupted SKUs to pending")
            
            # Process using chunked batch processor
            def status_callback(msg: str):
                self.logger.info(msg)
                # Update heartbeat periodically during processing
                if "Chunk" in msg and "completed" in msg:
                    self.update_heartbeat('processing', job_id)
                    # Log memory after each chunk
                    current_memory = self._get_memory_usage_mb()
                    self.logger.info(f"💾 Memory after chunk: {current_memory:.1f} MB (Δ{current_memory - initial_memory:+.1f} MB)")
            
            # Heartbeat callback for mid-chunk updates (every 3 products)
            def heartbeat_callback():
                self.update_heartbeat('processing', job_id)
            
            # Use configured max_workers (1 for Autoscale, 3 for Reserved VM)
            processor = BatchProcessor(status_callback, max_workers=self.max_workers, heartbeat_callback=heartbeat_callback)
            
            # Map update_mode to force_update parameter for backward compatibility
            # 'full' = force re-scrape everything
            # 'incremental' = smart update (new products + price/availability only)
            force_update = (update_mode == 'full')
            
            # Process in chunks
            results = processor.process_sku_list_chunked(
                job_id, 
                chunk_size=self.chunk_size,
                force_update=force_update,
                update_mode=update_mode
            )
            
            processor.close()
            
            # Log results
            self.log_event(job_id, 'job_completed', 
                          f"Completed: {results['successful']}/{results['total_products']} successful",
                          metadata={
                              'successful': results['successful'],
                              'failed': results['failed'],
                              'total_products': results['total_products'],
                              'processing_time': results['processing_time'],
                              'chunks_processed': results['chunks_processed']
                          })
            
            self.logger.info(f"Job #{job_id} completed: {results['successful']}/{results['total_products']} successful")

            # Task 2: Record per-job quality stats in update_statistics
            # This table was designed for this purpose but was never populated.
            # Having this data allows the health panel to show success/failure trends.
            self._record_update_statistics(job_id, category_code, results)
            
        except Exception as e:
            self.logger.error(f"Error processing job #{job_id}: {e}")
            self.log_event(job_id, 'job_failed', f"Error: {str(e)}")
            
            # Increment retry count
            conn = None
            try:
                conn = self._get_db_connection()
                cur = conn.cursor()
                
                cur.execute("""
                    UPDATE category_processing_jobs
                    SET retry_count = retry_count + 1,
                        status = CASE 
                            WHEN retry_count + 1 >= max_retries THEN 'failed'
                            ELSE 'queued'
                        END,
                        current_worker_id = NULL,
                        last_heartbeat = NULL
                    WHERE id = %s
                """, (job_id,))
                
                conn.commit()
                
            except Exception as db_error:
                self.logger.error(f"Failed to update job retry count: {db_error}")
                if conn:
                    conn.rollback()
            finally:
                if conn:
                    conn.close()
        
        finally:
            self.current_job_id = None
    
    def _record_update_statistics(self, job_id: int, category_code: str, results: dict):
        """
        Task 2: Persist per-job quality stats into update_statistics.
        Columns: job_id, category_code, total_checked, new_products,
                 price_changed, availability_changed, data_updated, unchanged, failed
        """
        conn = None
        try:
            conn = self._get_db_connection()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO update_statistics
                    (job_id, category_code, total_checked, new_products,
                     price_changed, availability_changed, data_updated, unchanged, failed)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                job_id,
                category_code,
                results.get('total_products', 0),
                results.get('new_products', 0),
                results.get('price_changes', 0),
                0,  # availability_changed — not separately tracked yet
                results.get('successful', 0),
                max(0, results.get('total_products', 0) - results.get('successful', 0) - results.get('failed', 0)),
                results.get('failed', 0),
            ))
            conn.commit()
            self.logger.info(f"Recorded update_statistics for job #{job_id}")
        except Exception as e:
            self.logger.error(f"Failed to record update_statistics: {e}")
            if conn:
                conn.rollback()
        finally:
            if conn:
                conn.close()

    def create_job(self, category_code: str, priority: int = 5):
        """Create a new job for a category"""
        conn = None
        try:
            conn = self._get_db_connection()
            cur = conn.cursor()
            
            # First, collect SKUs from category
            self.logger.info(f"Collecting SKUs from category {category_code}...")
            
            parser = RimiParser(lambda msg: self.logger.info(msg))
            all_skus = parser.collect_category_skus(category_code)
            
            if not all_skus:
                self.logger.error(f"No products found in category {category_code}")
                return None
            
            self.logger.info(f"Found {len(all_skus)} products in {category_code}")
            
            # Create job
            cur.execute("""
                INSERT INTO category_processing_jobs 
                (category_code, category_id, total_products, processed_count, status, priority, requested_by)
                VALUES (%s, NULL, %s, 0, 'queued', %s, %s)
                RETURNING id
            """, (category_code, len(all_skus), priority, f'worker_{self.worker_id}'))
            
            job_id = cur.fetchone()['id']
            
            # Log all SKUs as pending
            for sku in all_skus:
                cur.execute("""
                    INSERT INTO product_processing_log (job_id, sku, status)
                    VALUES (%s, %s, 'pending')
                """, (job_id, sku))
            
            conn.commit()
            
            self.logger.info(f"Created job #{job_id} for category {category_code} with {len(all_skus)} products")
            self.log_event(job_id, 'job_created', f"Job created for {category_code} with {len(all_skus)} products")
            
            return job_id
            
        except psycopg2.IntegrityError as e:
            if 'idx_unique_active_category' in str(e):
                self.logger.warning(f"Job already exists for category {category_code}")
                return None
            raise
        except Exception as e:
            self.logger.error(f"Failed to create job for {category_code}: {e}")
            if conn:
                conn.rollback()
            return None
        finally:
            if conn:
                conn.close()
    
    def run(self, mode: str = 'continuous', categories: List[str] = None):
        """Run worker in specified mode"""
        self.logger.info(f"Worker {self.worker_id} starting in {mode} mode")
        self.register_worker()
        
        try:
            if mode == 'single' and categories:
                # Process specific categories
                for cat in categories:
                    if not self.running:
                        break
                    
                    job_id = self.create_job(cat)
                    if job_id:
                        job = self.acquire_next_job()
                        if job:
                            self.process_job(job)
                
                # Refresh materialized view after processing categories
                if self.running:
                    self.refresh_product_ingredient_cards()
                
            elif mode == 'resume-all':
                # Process all incomplete jobs
                while self.running:
                    self.update_heartbeat('idle')
                    job = self.acquire_next_job()
                    
                    if job:
                        self.process_job(job)
                    else:
                        self.logger.info("No more jobs in queue, exiting")
                        self.refresh_product_ingredient_cards()
                        break
                    
            else:  # continuous
                # Continuously poll for jobs
                idle_sleep = 10
                
                while self.running:
                    self.update_heartbeat('idle')
                    job = self.acquire_next_job()
                    
                    if job:
                        self.process_job(job)
                    else:
                        self.logger.debug(f"No jobs available, sleeping {idle_sleep}s")
                        time.sleep(idle_sleep)
        
        finally:
            self.shutdown()
    
    def refresh_product_ingredient_cards(self):
        """Refresh the materialized view for product card data sharing"""
        conn = None
        try:
            self.logger.info("Refreshing product_ingredient_cards materialized view...")
            start_time = time.time()
            
            conn = self._get_db_connection()
            conn.autocommit = True
            cur = conn.cursor()
            
            cur.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY product_ingredient_cards")
            
            elapsed = time.time() - start_time
            self.logger.info(f"Materialized view refreshed in {elapsed:.1f}s")
            
        except Exception as e:
            self.logger.error(f"Failed to refresh materialized view: {e}")
        finally:
            if conn:
                conn.close()
    
    def shutdown(self):
        """Shutdown worker gracefully"""
        self.logger.info("Shutting down worker...")
        
        conn = None
        try:
            conn = self._get_db_connection()
            cur = conn.cursor()
            
            cur.execute("""
                UPDATE processing_workers
                SET status = 'stopped',
                    stopped_at = CURRENT_TIMESTAMP,
                    current_job_id = NULL
                WHERE worker_id = %s
            """, (self.worker_id,))
            
            conn.commit()
            self.logger.info(f"Worker {self.worker_id} shutdown complete")
            
        except Exception as e:
            self.logger.error(f"Error during shutdown: {e}")
            if conn:
                conn.rollback()
        finally:
            if conn:
                conn.close()


def main():
    parser = argparse.ArgumentParser(description='Category Processing Worker')
    parser.add_argument('--category', type=str, help='Process single category code')
    parser.add_argument('--categories', type=str, help='Process multiple categories (comma-separated)')
    parser.add_argument('--resume-all', action='store_true', help='Resume all incomplete jobs')
    parser.add_argument('--priority', type=int, default=5, help='Job priority (1-10, higher = more urgent)')
    parser.add_argument('--chunk-size', type=int, default=15, help='Number of products per chunk')
    parser.add_argument('--max-workers', type=int, default=3, help='Maximum concurrent workers (use 1 for Autoscale, 3 for Reserved VM)')
    parser.add_argument('--heartbeat-interval', type=int, default=30, help='Heartbeat interval in seconds')
    parser.add_argument('--log-dir', type=str, default='logs', help='Log directory')
    parser.add_argument('--worker-id', type=str, default=None, help='Worker ID (auto-generated if not provided)')
    parser.add_argument('--production', action='store_true', help='Use production database (PROD_DATABASE_URL) instead of development')
    parser.add_argument('--daemon', action='store_true', help='Run in daemon mode (keep running, wait for new jobs instead of exiting when queue is empty)')
    
    args = parser.parse_args()
    
    # Generate worker ID if not provided
    worker_id = args.worker_id or f"{socket.gethostname()}_{os.getpid()}_{int(time.time())}"
    
    # Create worker instance
    worker = ProcessingWorker(
        worker_id=worker_id,
        heartbeat_interval=args.heartbeat_interval,
        chunk_size=args.chunk_size,
        max_workers=args.max_workers,
        log_dir=args.log_dir,
        use_production=args.production
    )
    
    # Determine mode and categories
    if args.daemon:
        # Daemon mode - keep running and wait for new jobs
        worker.run(mode='continuous')
    elif args.resume_all:
        worker.run(mode='resume-all')
    elif args.category or args.categories:
        categories = []
        if args.category:
            categories.append(args.category)
        if args.categories:
            categories.extend(args.categories.split(','))
        worker.run(mode='single', categories=categories)
    else:
        # Default to continuous mode
        worker.run(mode='continuous')


if __name__ == '__main__':
    main()
