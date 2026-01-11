"""
Worker Refresh Snippet for Barbora Project
Add this method to your ProcessingWorker class in worker.py
"""

import time

def refresh_product_ingredient_cards(self):
    """
    Refresh the materialized view for product card data sharing.
    Call this after daily processing completes.
    
    IMPORTANT: Uses autocommit=True because REFRESH MATERIALIZED VIEW CONCURRENTLY
    cannot run inside a transaction block.
    """
    conn = None
    try:
        self.logger.info("Refreshing product_ingredient_cards materialized view...")
        start_time = time.time()
        
        conn = self._get_db_connection()
        conn.autocommit = True  # Required for REFRESH CONCURRENTLY
        cur = conn.cursor()
        
        cur.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY product_ingredient_cards")
        
        elapsed = time.time() - start_time
        self.logger.info(f"Materialized view refreshed in {elapsed:.1f}s")
        
    except Exception as e:
        self.logger.error(f"Failed to refresh materialized view: {e}")
    finally:
        if conn:
            conn.close()


# Where to call this in your worker.py:
#
# 1. In 'resume-all' mode - after queue is empty:
#     else:
#         self.logger.info("No more jobs in queue, exiting")
#         self.refresh_product_ingredient_cards()  # <-- Add here
#         break
#
# 2. In 'single' mode - after processing categories:
#     # Process specific categories
#     for cat in categories:
#         ...
#     
#     # Refresh materialized view after processing categories
#     if self.running:
#         self.refresh_product_ingredient_cards()  # <-- Add here
