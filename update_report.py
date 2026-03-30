#!/usr/bin/env python3
"""
Update Report Module - Track and log daily update results
Monitors product changes, price changes, new products, and generates summary reports
"""
import os
import logging
import psycopg2
from psycopg2.extras import RealDictCursor, Json
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class UpdateReport:
    """Track and report daily update statistics"""
    
    def __init__(self, db_url: Optional[str] = None):
        self.db_url = db_url or os.environ['DATABASE_URL']
    
    def _get_db_connection(self):
        """Get database connection"""
        return psycopg2.connect(self.db_url, cursor_factory=RealDictCursor)
    
    def generate_update_report(self, start_time: datetime, end_time: Optional[datetime] = None) -> Dict:
        """
        Generate comprehensive update report for a time period
        
        Args:
            start_time: Report start time
            end_time: Report end time (defaults to now)
        
        Returns:
            Dictionary with update statistics
        """
        if end_time is None:
            end_time = datetime.now()
        
        conn = None
        try:
            conn = self._get_db_connection()
            cur = conn.cursor()
            
            report = {
                'start_time': start_time,
                'end_time': end_time,
                'duration_minutes': (end_time - start_time).total_seconds() / 60,
                'products_updated': 0,
                'products_added': 0,
                'products_removed': 0,
                'price_changes': [],
                'availability_changes': [],
                'ingredient_changes': [],
                'nutrition_changes': [],
                'photo_changes': [],
                'categories_processed': 0,
                'jobs_completed': 0,
                'jobs_failed': 0,
                'jobs_stuck': 0,
                'stuck_jobs': [],
                'errors': []
            }
            
            # Get job statistics
            cur.execute("""
                SELECT 
                    COUNT(*) FILTER (WHERE status = 'completed') as completed,
                    COUNT(*) FILTER (WHERE status = 'failed') as failed,
                    COUNT(DISTINCT category_code) as categories
                FROM category_processing_jobs
                WHERE last_updated BETWEEN %s AND %s
            """, (start_time, end_time))
            
            job_stats = cur.fetchone()
            if job_stats:
                report['jobs_completed'] = job_stats['completed'] or 0
                report['jobs_failed'] = job_stats['failed'] or 0
                report['categories_processed'] = job_stats['categories'] or 0
            
            # Detect stuck jobs with robust criteria to avoid false positives
            # 
            # Workers send heartbeats every 30 seconds (throttled to prevent excessive DB writes)
            # BatchProcessor calls heartbeat after each product, but worker throttles to 30s interval
            # 
            # A job is truly stuck if ALL of the following are true:
            # 1. Status is 'in_progress' for > 15 minutes (grace period for new jobs)
            # 2. Worker heartbeat is stale (> 15 minutes with 30s heartbeat interval)
            # 3. Worker is completely dead (> 30 minutes no heartbeat = 60x heartbeat interval)
            #
            # With 30-second heartbeats:
            # - Healthy workers: heartbeat every 30 seconds (regardless of product speed)
            # - 15-minute threshold = 30 heartbeats missed = clearly stuck
            # - 30-minute threshold = 60 heartbeats missed = completely dead
            cur.execute("""
                WITH job_progress AS (
                    SELECT 
                        j.id,
                        j.category_code,
                        j.status,
                        j.processed_count,
                        j.last_updated,
                        w.last_heartbeat,
                        w.worker_id,
                        -- Calculate time since job started
                        EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - j.last_updated))/60 as minutes_in_progress,
                        -- Calculate time since last heartbeat
                        EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - COALESCE(w.last_heartbeat, j.last_updated)))/60 as minutes_since_heartbeat
                    FROM category_processing_jobs j
                    LEFT JOIN processing_workers w ON j.id = w.current_job_id
                    WHERE j.status = 'in_progress'
                )
                SELECT 
                    id as job_id,
                    category_code,
                    worker_id,
                    minutes_in_progress,
                    minutes_since_heartbeat,
                    processed_count
                FROM job_progress
                WHERE 
                    -- Job has been running for at least 15 minutes (grace period)
                    minutes_in_progress > 15
                    -- AND heartbeat is stale (> 15 minutes with mid-chunk heartbeats)
                    AND minutes_since_heartbeat > 15
                    -- AND either no worker assigned OR worker is truly dead
                    AND (
                        worker_id IS NULL
                        OR minutes_since_heartbeat > 30  -- Worker heartbeat dead for >30 min (10x heartbeat interval)
                    )
                ORDER BY minutes_in_progress DESC
            """)
            
            stuck_jobs = cur.fetchall()
            report['jobs_stuck'] = len(stuck_jobs)
            report['stuck_jobs'] = [
                {
                    'job_id': sj['job_id'],
                    'category': sj['category_code'],
                    'hours_stuck': float(sj['minutes_in_progress']) / 60,
                    'worker_id': sj['worker_id'],
                    'processed_count': sj['processed_count']
                }
                for sj in stuck_jobs
            ]
            
            # Get product update statistics
            cur.execute("""
                SELECT 
                    COUNT(*) FILTER (WHERE created_at BETWEEN %s AND %s) as added,
                    COUNT(*) FILTER (WHERE updated_at BETWEEN %s AND %s AND created_at < %s) as updated
                FROM products
            """, (start_time, end_time, start_time, end_time, start_time))
            
            product_stats = cur.fetchone()
            if product_stats:
                report['products_added'] = product_stats['added'] or 0
                report['products_updated'] = product_stats['updated'] or 0
            
            # Get price changes
            cur.execute("""
                WITH price_changes_cte AS (
                    SELECT 
                        p.sku,
                        p.name,
                        ph.price,
                        ph.recorded_at,
                        LAG(ph.price) OVER (PARTITION BY ph.product_id ORDER BY ph.recorded_at) as prev_price
                    FROM product_price_history ph
                    JOIN products p ON p.product_id = ph.product_id
                    WHERE ph.recorded_at BETWEEN %s AND %s
                )
                SELECT DISTINCT ON (sku) sku, name, prev_price, price
                FROM price_changes_cte
                WHERE prev_price IS NOT NULL 
                AND prev_price != price
                ORDER BY sku, recorded_at DESC
                LIMIT 100
            """, (start_time, end_time))
            
            price_changes = cur.fetchall()
            report['price_changes'] = [
                {
                    'sku': pc['sku'],
                    'name': pc['name'],
                    'old_price': float(pc['prev_price']),
                    'new_price': float(pc['price']),
                    'change': float(pc['price']) - float(pc['prev_price'])
                }
                for pc in price_changes
            ]
            
            # Get availability changes (products that went in/out of stock)
            cur.execute("""
                WITH avail_changes AS (
                    SELECT 
                        product_id,
                        is_available,
                        LAG(is_available) OVER (PARTITION BY product_id ORDER BY recorded_at) as prev_available,
                        recorded_at
                    FROM product_price_history
                    WHERE recorded_at BETWEEN %s AND %s
                )
                SELECT 
                    COUNT(*) FILTER (WHERE is_available = true AND prev_available = false) as back_in_stock,
                    COUNT(*) FILTER (WHERE is_available = false AND prev_available = true) as out_of_stock
                FROM avail_changes
                WHERE prev_available IS NOT NULL
            """, (start_time, end_time))
            
            avail_stats = cur.fetchone()
            if avail_stats:
                report['availability_changes'] = {
                    'back_in_stock': avail_stats['back_in_stock'] or 0,
                    'out_of_stock': avail_stats['out_of_stock'] or 0
                }
            
            # Count products with changes in different areas
            # Note: Simplified - just count updates during period
            cur.execute("""
                SELECT 
                    COUNT(*) FILTER (WHERE nutrition_source IS NOT NULL AND updated_at BETWEEN %s AND %s) as nutrition_updates
                FROM products
            """, (start_time, end_time))
            
            change_stats = cur.fetchone()
            if change_stats:
                report['nutrition_changes'] = change_stats['nutrition_updates'] or 0
            
            # Ingredient and photo changes can be tracked if needed by checking related tables
            # For now, set to 0 (can be enhanced later)
            report['ingredient_changes'] = 0
            report['photo_changes'] = 0
            
            # Get errors from job events
            cur.execute("""
                SELECT 
                    j.category_code,
                    je.message,
                    je.created_at
                FROM job_events je
                JOIN category_processing_jobs j ON j.id = je.job_id
                WHERE je.event_type = 'error'
                AND je.created_at BETWEEN %s AND %s
                LIMIT 50
            """, (start_time, end_time))
            
            errors = cur.fetchall()
            report['errors'] = [
                {
                    'category': e['category_code'],
                    'message': e['message'],
                    'time': e['created_at']
                }
                for e in errors
            ]
            
            return report
            
        except Exception as e:
            print(f"Error generating report: {e}")
            return None
        finally:
            if conn:
                conn.close()
    
    def save_report_to_database(self, report: Dict, update_type: str = 'daily') -> Optional[int]:
        """
        Save report to daily_update_logs table
        
        Args:
            report: Report dictionary from generate_update_report
            update_type: Type of update (daily, manual, etc.)
        
        Returns:
            Log ID or None if failed
        """
        conn = None
        try:
            conn = self._get_db_connection()
            cur = conn.cursor()
            
            cur.execute("""
                INSERT INTO daily_update_logs (
                    update_type,
                    start_time,
                    end_time,
                    duration_minutes,
                    categories_processed,
                    jobs_completed,
                    jobs_failed,
                    products_added,
                    products_updated,
                    products_removed,
                    price_changes_count,
                    availability_changes,
                    errors_count,
                    summary
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                RETURNING id
            """, (
                update_type,
                report['start_time'],
                report['end_time'],
                report['duration_minutes'],
                report['categories_processed'],
                report['jobs_completed'],
                report['jobs_failed'],
                report['products_added'],
                report['products_updated'],
                report['products_removed'],
                len(report['price_changes']),
                Json(report.get('availability_changes') or {}),
                len(report['errors']),
                self._generate_summary_text(report)
            ))
            
            log_id = cur.fetchone()['id']
            conn.commit()
            
            print(f"✅ Report saved to database (ID: {log_id})")
            return log_id
            
        except Exception as e:
            logger.error(f"Error saving report to database: {e}", exc_info=True)
            print(f"❌ Error saving report: {e}")
            if conn:
                conn.rollback()
            return None
        finally:
            if conn:
                conn.close()
    
    def _generate_summary_text(self, report: Dict) -> str:
        """Generate human-readable summary text"""
        lines = []
        lines.append(f"Update completed in {report['duration_minutes']:.1f} minutes")
        lines.append(f"Processed {report['categories_processed']} categories ({report['jobs_completed']} jobs)")
        
        if report['products_added']:
            lines.append(f"Added {report['products_added']} new products")
        
        if report['products_updated']:
            lines.append(f"Updated {report['products_updated']} products")
        
        if report['price_changes']:
            lines.append(f"Detected {len(report['price_changes'])} price changes")
        
        if report['errors']:
            lines.append(f"⚠️ {len(report['errors'])} errors occurred")
        
        return "; ".join(lines)
    
    def print_report(self, report: Dict):
        """Print formatted report to console"""
        print("\n" + "=" * 80)
        print(f"📊 UPDATE REPORT - {report['start_time'].strftime('%Y-%m-%d %H:%M')}")
        print("=" * 80)
        
        print(f"\n⏱️  Duration: {report['duration_minutes']:.1f} minutes")
        print(f"📦 Categories: {report['categories_processed']}")
        print(f"✅ Jobs Completed: {report['jobs_completed']}")
        
        if report['jobs_failed']:
            print(f"❌ Jobs Failed: {report['jobs_failed']}")
        
        if report.get('jobs_stuck', 0) > 0:
            print(f"⚠️  Jobs Stuck: {report['jobs_stuck']}")
            for sj in report.get('stuck_jobs', [])[:5]:
                print(f"   Job #{sj['job_id']} ({sj['category']}): stuck for {sj['hours_stuck']:.1f} hours")
        
        print(f"\n📈 Product Statistics:")
        print(f"   New products: {report['products_added']}")
        print(f"   Updated: {report['products_updated']}")
        
        if report['products_removed']:
            print(f"   Removed: {report['products_removed']}")
        
        if report['price_changes']:
            print(f"\n💰 Price Changes ({len(report['price_changes'])}):")
            for pc in report['price_changes'][:10]:  # Show first 10
                change_symbol = "↑" if pc['change'] > 0 else "↓"
                print(f"   {change_symbol} {pc['name'][:50]}: €{pc['old_price']:.2f} → €{pc['new_price']:.2f}")
            
            if len(report['price_changes']) > 10:
                print(f"   ... and {len(report['price_changes']) - 10} more")
        
        if report.get('availability_changes'):
            avail = report['availability_changes']
            print(f"\n📊 Availability:")
            print(f"   Back in stock: {avail.get('back_in_stock', 0)}")
            print(f"   Out of stock: {avail.get('out_of_stock', 0)}")
        
        if report['errors']:
            print(f"\n⚠️  Errors ({len(report['errors'])}):")
            for err in report['errors'][:5]:  # Show first 5
                print(f"   {err['category']}: {err['message'][:60]}")
            
            if len(report['errors']) > 5:
                print(f"   ... and {len(report['errors']) - 5} more")
        
        print("\n" + "=" * 80)


def main():
    """Test report generation"""
    import argparse
    from datetime import timedelta
    
    parser = argparse.ArgumentParser(description='Generate update report')
    parser.add_argument('--hours', type=int, default=24, help='Report time window in hours (default: 24)')
    parser.add_argument('--production', action='store_true', help='Use production database')
    parser.add_argument('--save', action='store_true', help='Save report to database')
    
    args = parser.parse_args()
    
    # Select database
    db_url = None
    if args.production:
        db_url = os.environ.get('PROD_DATABASE_URL')
        if not db_url:
            print("❌ PROD_DATABASE_URL not set")
            return
        print("🚀 Using production database")
    else:
        db_url = os.environ['DATABASE_URL']
        print("🔧 Using development database")
    
    # Generate report
    reporter = UpdateReport(db_url)
    end_time = datetime.now()
    start_time = end_time - timedelta(hours=args.hours)
    
    print(f"Generating report for last {args.hours} hours...")
    report = reporter.generate_update_report(start_time, end_time)
    
    if report:
        reporter.print_report(report)
        
        if args.save:
            reporter.save_report_to_database(report, update_type='manual')
    else:
        print("❌ Failed to generate report")


if __name__ == '__main__':
    main()
