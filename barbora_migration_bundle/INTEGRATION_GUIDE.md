# AI Ingredient Categorization Migration Bundle

This bundle adds AI-powered ingredient categorization and NOVA4 ultra-processed food marker detection to the Barbora scraper project.

## What's Included

| File | Purpose |
|------|---------|
| `01_alter_ingredient_analysis.sql` | Adds AI columns to existing ingredient_analysis table |
| `02_create_materialized_view.sql` | Creates product_ingredient_cards view for data sharing |
| `combined_ingredient_analyzer.py` | Main AI analyzer (categorization + suspicion in one pass) |
| `worker_refresh_snippet.py` | Code snippet to add materialized view refresh to worker |

## Step-by-Step Integration

### 1. Run Database Migrations

Execute in order:
```bash
psql $DATABASE_URL -f 01_alter_ingredient_analysis.sql
psql $DATABASE_URL -f 02_create_materialized_view.sql
```

### 2. Copy Analyzer Code

Copy `combined_ingredient_analyzer.py` to your project root.

### 3. Install/Verify Gemini Integration

The analyzer uses Google Gemini AI. Ensure you have the integration installed:
- Go to Replit → Tools → Integrations → search "Gemini"
- Install the Python Gemini integration
- This provides `AI_INTEGRATIONS_GEMINI_API_KEY` automatically

### 4. Add UI Section to main.py

Add this import and section to your Streamlit app:

```python
from combined_ingredient_analyzer import (
    get_analysis_stats, run_test_batch, run_full_analysis, 
    reset_all_analysis, batch_update_ingredients, BATCH_SIZE
)

def section_ingredient_analysis():
    st.header("🧪 Combined Ingredient Analysis")
    
    stats = get_analysis_stats()
    if stats:
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total Ingredients", stats['total'])
        with col2:
            st.metric("🌿 Natural", stats['natural_count'])
        with col3:
            st.metric("🏭 Processed", stats['processed_count'])
        with col4:
            st.metric("❓ Unanalyzed", stats['unanalyzed'])
        
        st.subheader("Suspicion Levels")
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("🔴 Avoid", stats['avoid_count'])
        with col2:
            st.metric("🟠 Limit", stats['limit_count'])
        with col3:
            st.metric("🟡 Caution", stats['caution_count'])
        with col4:
            st.metric("✅ Clean", stats['clean_count'])
    
    # Test batch button
    if st.button("🧪 Run Test Batch (40 ingredients)"):
        with st.spinner("Analyzing..."):
            results = run_test_batch(batch_count=1)
            st.session_state.test_results = results
    
    # Full analysis button
    if st.button("🚀 Run Full Analysis", type="primary"):
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        def update_progress(processed, total):
            progress_bar.progress(processed / total)
            status_text.text(f"Processed {processed}/{total} ingredients")
        
        result = run_full_analysis(progress_callback=update_progress)
        st.success(f"Completed! Processed {result.get('processed', 0)} ingredients")
```

### 5. Add Worker Refresh (Optional)

To automatically refresh the materialized view after daily updates, add this method to your worker class:

```python
def refresh_product_ingredient_cards(self):
    """Refresh the materialized view for product card data sharing"""
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
```

Call it at the end of your job processing loop:
```python
# After processing completes
self.refresh_product_ingredient_cards()
```

## Data Sharing Contract

The `product_ingredient_cards` materialized view provides:

```sql
SELECT sku, name, ingredients, natural_count, processed_count, avoid_count
FROM product_ingredient_cards
WHERE sku = 'YOUR_SKU';
```

**Fields:**
- `sku`, `name`, `category_id`, `category_name`: Product identification
- `ingredients`: JSONB array (always `[]` if empty, never NULL)
  - `id`: Stable foreign key
  - `name`: Cleaned ingredient name
  - `category`: 'natural', 'processed', 'uncategorized'
  - `is_processed`: Boolean
  - `suspicion_level`: 'avoid'/'limit'/'caution'/'clean'/null
  - `suspicion_category`: Type of concern
  - `health_note`: Latvian health warning
- `natural_count`, `processed_count`: Summary counts
- `avoid_count`, `limit_count`, `caution_count`: Risk indicators

**Refresh after daily updates:**
```sql
REFRESH MATERIALIZED VIEW CONCURRENTLY product_ingredient_cards;
```

## AI Analysis Logic

| Category | Suspicion Level | Meaning |
|----------|-----------------|---------|
| natural | NULL | Natural ingredient, no suspicion applicable |
| processed + suspicious | avoid/limit/caution | Ultra-processed marker detected |
| processed + not suspicious | clean | Processed but not concerning |
| uncategorized | NULL | Not yet analyzed |

## Configuration

- **Batch size**: 40 ingredients per API call (optimized for accuracy)
- **AI Model**: Gemini 2.0 Flash
- **Cost**: ~$0.005-0.02 per batch of 40 ingredients

## Troubleshooting

**"AI_INTEGRATIONS_GEMINI_API_KEY not found"**
→ Install the Gemini integration from Replit Tools → Integrations

**"Cannot refresh materialized view concurrently"**
→ Ensure the unique index exists: `CREATE UNIQUE INDEX idx_product_ingredient_cards_sku ON product_ingredient_cards(sku);`

**Worker refresh fails**
→ Make sure `conn.autocommit = True` is set before the REFRESH command
