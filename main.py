"""
Rimi Product Scraper - Redesigned UI
Two-section interface: Category Processing + Product View
"""

import streamlit as st
from product_view_db import ProductViewDatabase
import time
import os

st.set_page_config(
    page_title="Rimi Product Scraper",
    page_icon="🛒",
    layout="wide"
)

# Session state initialization
if 'view_mode' not in st.session_state:
    st.session_state.view_mode = 'category_processing'
if 'selected_product_id' not in st.session_state:
    st.session_state.selected_product_id = None
if 'current_page' not in st.session_state:
    st.session_state.current_page = 1
if 'selected_category_id' not in st.session_state:
    st.session_state.selected_category_id = None
if 'expanded_categories' not in st.session_state:
    st.session_state.expanded_categories = set()


def render_nutri_score_badge(grade: str) -> str:
    """Render Nutri-Score badge HTML"""
    if not grade:
        return ""
    
    colors = {
        'A': '#038141',
        'B': '#85BB2F',
        'C': '#FECB02',
        'D': '#EE8100',
        'E': '#E63E11'
    }
    
    color = colors.get(grade, '#999')
    return f'<div style="background-color: {color}; color: white; font-weight: bold; padding: 4px 8px; border-radius: 4px; display: inline-block; font-size: 14px;">{grade}</div>'


def render_product_card(product: dict) -> None:
    """Render a single product card in grid"""
    
    # Product image
    image_url = product.get('photo_url')
    if image_url:
        st.image(image_url, use_container_width=True)
    else:
        st.markdown("<div style='background:#f0f0f0; height:150px; display:flex; align-items:center; justify-content:center;'>No Image</div>", unsafe_allow_html=True)
    
    # Nutri-Score badge
    nutri_grade = product.get('nutri_score_grade')
    if nutri_grade:
        st.markdown(render_nutri_score_badge(nutri_grade), unsafe_allow_html=True)
    
    # Product name (clickable)
    product_name = product.get('name', 'Unknown Product')
    if st.button(f"**{product_name[:50]}**", key=f"prod_{product['product_id']}", use_container_width=True):
        st.session_state.selected_product_id = product['product_id']
        st.rerun()
    
    # Quantity
    qty = product.get('quantity_value')
    unit = product.get('quantity_unit', '')
    if qty:
        st.caption(f"{qty}{unit}")
    
    # Nutrition values
    if product.get('carbs_sugars') is not None:
        st.caption(f"🍬 Cukurs: {product['carbs_sugars']}g")
    if product.get('fat_total') is not None:
        st.caption(f"🧈 Tauki: {product['fat_total']}g")
    if product.get('protein') is not None:
        st.caption(f"💪 Olbaltumvielas: {product['protein']}g")
    if product.get('salt') is not None:
        st.caption(f"🧂 Sāls: {product['salt']}g")


def render_category_tree_node(category: dict, db: ProductViewDatabase, level: int = 0) -> None:
    """Recursively render category tree node with expand/collapse"""
    
    indent = "　" * level
    category_id = category['category_id']
    has_children = len(category.get('children', [])) > 0
    is_expanded = category_id in st.session_state.expanded_categories
    
    # Category display
    col1, col2 = st.columns([4, 1])
    
    with col1:
        # Expand/collapse icon
        if has_children:
            icon = "▼" if is_expanded else "▶"
            if st.button(f"{indent}{icon} {category['name_lv']}", key=f"cat_{category_id}", use_container_width=True):
                if is_expanded:
                    st.session_state.expanded_categories.discard(category_id)
                else:
                    st.session_state.expanded_categories.add(category_id)
                st.rerun()
        else:
            if st.button(f"{indent}• {category['name_lv']}", key=f"cat_{category_id}", use_container_width=True):
                st.session_state.selected_category_id = category_id
                st.session_state.current_page = 1
                st.rerun()
    
    with col2:
        # Product count badge
        product_count = category.get('product_count', 0)
        if product_count > 0:
            st.caption(f"({product_count})")
    
    # Render children if expanded
    if is_expanded and has_children:
        for child in category['children']:
            render_category_tree_node(child, db, level + 1)


def section_category_processing():
    """Section 1: Category Processing"""
    st.header("📦 Category Processing")
    
    col1, col2 = st.columns([3, 1])
    
    with col1:
        category_code = st.text_input(
            "Category Code",
            placeholder="e.g., SH-11-6-19, SH-7",
            help="Enter full category code (e.g., SH-11-6-19)"
        )
    
    with col2:
        st.write("")
        st.write("")
        force_update = st.checkbox("Force Update", help="Overwrite existing data")
    
    # Check for incomplete jobs
    incomplete_job = None
    if category_code:
        from progress_manager import ProgressManager
        progress_mgr = ProgressManager()
        incomplete_job = progress_mgr.find_incomplete_job(category_code)
        
        if incomplete_job:
            st.info(f"📌 Found incomplete processing job for this category")
            col_resume1, col_resume2, col_resume3 = st.columns(3)
            with col_resume1:
                st.metric("Total Products", incomplete_job['total_products'])
            with col_resume2:
                st.metric("Completed", incomplete_job['processed_count'])
            with col_resume3:
                remaining = incomplete_job['total_products'] - incomplete_job['processed_count']
                st.metric("Remaining", remaining)
    
    # Job queueing controls
    col_btn1, col_btn2, col_btn3 = st.columns(3)
    
    with col_btn1:
        priority = st.number_input("Priority", min_value=1, max_value=10, value=5, help="Higher = more urgent")
    
    with col_btn2:
        st.write("")
        st.write("")
        queue_job = st.button("📥 Queue Job", type="primary", disabled=not category_code)
    
    with col_btn3:
        st.write("")
        st.write("")
        if incomplete_job:
            st.info(f"Job #{incomplete_job['job_id']} in queue")
    
    if queue_job:
        from core_parser import RimiParser
        import psycopg2
        
        with st.spinner("Collecting products and creating job..."):
            try:
                # Collect SKUs from category
                parser = RimiParser(lambda msg: st.text(msg))
                all_skus = parser.collect_category_skus(category_code)
                
                if not all_skus:
                    st.error(f"No products found in category {category_code}")
                else:
                    # Create job in database
                    conn = psycopg2.connect(os.environ['DATABASE_URL'])
                    cur = conn.cursor()
                    
                    try:
                        # Lookup category_id from normalized_categories
                        cur.execute("""
                            SELECT category_id FROM normalized_categories 
                            WHERE rimi_category_code = %s
                        """, (category_code.upper(),))
                        cat_result = cur.fetchone()
                        cat_id = cat_result[0] if cat_result else None
                        
                        # Determine update mode based on Force Update checkbox
                        update_mode = 'full' if force_update else 'incremental'
                        
                        # Create job
                        cur.execute("""
                            INSERT INTO category_processing_jobs 
                            (category_code, category_id, total_products, processed_count, status, priority, requested_by, update_mode)
                            VALUES (%s, %s, %s, 0, 'queued', %s, 'streamlit_ui', %s)
                            RETURNING id
                        """, (category_code, cat_id, len(all_skus), priority, update_mode))
                        
                        job_id = cur.fetchone()[0]
                        
                        # Log all SKUs as pending
                        for sku in all_skus:
                            cur.execute("""
                                INSERT INTO product_processing_log (job_id, sku, status)
                                VALUES (%s, %s, 'pending')
                            """, (job_id, sku))
                        
                        # Log event
                        cur.execute("""
                            INSERT INTO job_events (job_id, event_type, message)
                            VALUES (%s, 'job_created', %s)
                        """, (job_id, f"Job created via Streamlit UI for {category_code} with {len(all_skus)} products (priority: {priority})"))
                        
                        conn.commit()
                        
                        st.success(f"✅ Job #{job_id} created successfully!")
                        st.info(f"📦 Queued {len(all_skus)} products from category {category_code}")
                        st.info(f"🔧 Run the worker to process: `python worker.py --resume-all`")
                        
                        with st.expander("View job details"):
                            st.json({
                                "job_id": job_id,
                                "category_code": category_code,
                                "total_products": len(all_skus),
                                "priority": priority,
                                "status": "queued"
                            })
                        
                    except psycopg2.IntegrityError as e:
                        if 'idx_unique_active_category' in str(e):
                            st.warning(f"⚠️ Job already exists for category {category_code}")
                        else:
                            raise
                    finally:
                        conn.close()
                        
            except Exception as e:
                st.error(f"❌ Error creating job: {str(e)}")
                import traceback
                with st.expander("Error details"):
                    st.code(traceback.format_exc())
    
    st.divider()
    
    st.subheader("🚀 Queue All Categories")
    
    all_force_update = st.checkbox("Force Update All", help="Overwrite existing data for all categories", key="all_force_update")
    
    col_all1, col_all2 = st.columns([1, 3])
    
    with col_all1:
        if st.button("📦 Queue All Level 2 Categories", type="primary"):
            from core_parser import RimiParser
            import psycopg2
            
            conn = psycopg2.connect(os.environ['DATABASE_URL'])
            cur = conn.cursor()
            
            try:
                cur.execute("""
                    SELECT category_id, rimi_category_code, name_lv 
                    FROM normalized_categories 
                    WHERE level = 2 
                    ORDER BY rimi_category_code
                """)
                all_categories = cur.fetchall()
                
                if not all_categories:
                    st.error("No level 2 categories found")
                else:
                    progress_bar = st.progress(0)
                    status_text = st.empty()
                    
                    parser = RimiParser(lambda msg: None)
                    update_mode = 'full' if all_force_update else 'incremental'
                    
                    total_jobs = 0
                    total_products = 0
                    skipped = 0
                    
                    for i, (cat_id, cat_code, cat_name) in enumerate(all_categories):
                        progress_bar.progress((i + 1) / len(all_categories))
                        status_text.text(f"Processing {cat_code}: {cat_name}...")
                        
                        try:
                            all_skus = parser.collect_category_skus(cat_code)
                            
                            if all_skus:
                                cur.execute("""
                                    INSERT INTO category_processing_jobs 
                                    (category_code, category_id, total_products, processed_count, status, priority, requested_by, update_mode)
                                    VALUES (%s, %s, %s, 0, 'queued', 5, 'streamlit_bulk', %s)
                                    RETURNING id
                                """, (cat_code, cat_id, len(all_skus), update_mode))
                                
                                job_id = cur.fetchone()[0]
                                
                                for sku in all_skus:
                                    cur.execute("""
                                        INSERT INTO product_processing_log (job_id, sku, status)
                                        VALUES (%s, %s, 'pending')
                                    """, (job_id, sku))
                                
                                cur.execute("""
                                    INSERT INTO job_events (job_id, event_type, message)
                                    VALUES (%s, 'job_created', %s)
                                """, (job_id, f"Bulk job for {cat_code} with {len(all_skus)} products"))
                                
                                conn.commit()
                                total_jobs += 1
                                total_products += len(all_skus)
                                
                        except psycopg2.IntegrityError:
                            conn.rollback()
                            skipped += 1
                        except Exception as e:
                            conn.rollback()
                            st.warning(f"Error for {cat_code}: {str(e)}")
                    
                    status_text.empty()
                    progress_bar.empty()
                    
                    st.success(f"✅ Created {total_jobs} jobs with {total_products} total products!")
                    if skipped > 0:
                        st.info(f"⏭️ Skipped {skipped} categories (already have active jobs)")
                    st.info("🔧 Run on Reserved VM: `python worker.py --daemon --chunk-size 15 --max-workers 3`")
                    
            except Exception as e:
                st.error(f"Error: {str(e)}")
                import traceback
                st.code(traceback.format_exc())
            finally:
                conn.close()
    
    with col_all2:
        st.caption("This will queue jobs for all 75 level 2 categories. Each category will be processed by the worker.")
    
    # Help section
    with st.expander("ℹ️ Help"):
        st.markdown("""
        **Category Processing** allows you to scrape and update product data:
        
        - Enter a full category code (e.g., SH-11-6-19) for single category
        - Use "Queue All Level 2 Categories" to process all 75 categories at once
        - Toggle Force Update to overwrite existing data
        - Processing is automatic with category extraction from product pages
        
        **Worker Commands for Reserved VM:**
        ```
        python worker.py --daemon --chunk-size 15 --max-workers 3 --heartbeat-interval 30
        ```
        """)


def section_product_view():
    """Section 2: Product View with hierarchical categories and grid"""
    st.header("🛍️ Product Browser")
    
    # Check if viewing product details
    if st.session_state.selected_product_id:
        render_product_detail_view()
        return
    
    db = ProductViewDatabase()
    
    # Build category tree with product counts
    category_tree = db.build_category_tree()
    product_counts = db.get_category_product_counts()
    
    # Add product counts to tree
    def add_counts(categories):
        for cat in categories:
            cat['product_count'] = product_counts.get(cat['category_id'], 0)
            if cat['children']:
                add_counts(cat['children'])
    
    add_counts(category_tree)
    
    # Layout: Sidebar (categories) + Main (products)
    col_sidebar, col_main = st.columns([1, 3])
    
    with col_sidebar:
        st.subheader("📂 Kategorijas")
        
        # "All Products" button
        if st.button("📋 Visi produkti", use_container_width=True):
            st.session_state.selected_category_id = None
            st.session_state.current_page = 1
            st.rerun()
        
        st.divider()
        
        # Render category tree
        for root_category in category_tree:
            render_category_tree_node(root_category, db, level=0)
    
    with col_main:
        # Get products for selected category
        products, total = db.get_products_by_category(
            category_id=st.session_state.selected_category_id,
            page=st.session_state.current_page,
            page_size=20,
            include_subcategories=True
        )
        
        # Display category name
        if st.session_state.selected_category_id:
            category_query = """
            SELECT name_lv, rimi_category_code 
            FROM normalized_categories 
            WHERE category_id = %s
            """
            db._ensure_connection()
            with db.connection.cursor() as cursor:
                cursor.execute(category_query, (st.session_state.selected_category_id,))
                cat_info = cursor.fetchone()
                if cat_info:
                    st.subheader(f"{cat_info['name_lv']} ({cat_info['rimi_category_code']})")
        else:
            st.subheader("Visi produkti")
        
        # Product count
        st.caption(f"Kopā: {total} produkti")
        
        # Pagination controls (top)
        total_pages = (total + 19) // 20
        if total_pages > 1:
            col1, col2, col3 = st.columns([1, 2, 1])
            with col1:
                if st.button("◀ Previous", disabled=st.session_state.current_page == 1):
                    st.session_state.current_page -= 1
                    st.rerun()
            with col2:
                st.write(f"Lapa {st.session_state.current_page} no {total_pages}")
            with col3:
                if st.button("Next ▶", disabled=st.session_state.current_page >= total_pages):
                    st.session_state.current_page += 1
                    st.rerun()
        
        st.divider()
        
        # Product grid (4 columns x 5 rows)
        if products:
            # Render in rows of 4
            for row in range(0, len(products), 4):
                cols = st.columns(4)
                for col_idx, col in enumerate(cols):
                    product_idx = row + col_idx
                    if product_idx < len(products):
                        with col:
                            render_product_card(products[product_idx])
        else:
            st.info("Nav produktu šajā kategorijā")
        
        # Pagination controls (bottom)
        if total_pages > 1:
            st.divider()
            col1, col2, col3 = st.columns([1, 2, 1])
            with col1:
                if st.button("◀ Prev", disabled=st.session_state.current_page == 1, key="prev_bottom"):
                    st.session_state.current_page -= 1
                    st.rerun()
            with col2:
                st.write(f"Lapa {st.session_state.current_page} no {total_pages}")
            with col3:
                if st.button("Next ▶", disabled=st.session_state.current_page >= total_pages, key="next_bottom"):
                    st.session_state.current_page += 1
                    st.rerun()
    
    db.close()


def render_product_detail_view():
    """Render detailed product view (similar to reference app)"""
    
    db = ProductViewDatabase()
    product = db.get_product_details(st.session_state.selected_product_id)
    
    if not product:
        st.error("Product not found")
        if st.button("← Atpakaļ"):
            st.session_state.selected_product_id = None
            st.rerun()
        db.close()
        return
    
    # Back button
    if st.button("← Atpakaļ uz produktu sarakstu"):
        st.session_state.selected_product_id = None
        st.rerun()
    
    st.divider()
    
    # Product header
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.title(product['name'])
        st.caption(f"SKU: {product['sku']}")
        if product.get('quantity_value'):
            st.caption(f"Daudzums: {product['quantity_value']}{product.get('quantity_unit', '')}")
    
    with col2:
        # Nutri-Score
        if product.get('nutri_score_grade'):
            st.markdown(render_nutri_score_badge(product['nutri_score_grade']), unsafe_allow_html=True)
            if product.get('nutri_score_points') is not None:
                st.caption(f"Punkti: {product['nutri_score_points']}")
        
        # Price
        if product.get('price'):
            st.metric("Cena", f"€{product['price']:.2f}")
    
    st.divider()
    
    # Product images
    if product.get('photos'):
        st.subheader("📸 Attēli")
        cols = st.columns(min(len(product['photos']), 3))
        for idx, photo_url in enumerate(product['photos'][:3]):
            with cols[idx]:
                st.image(photo_url, use_container_width=True)
    
    # Nutrition information
    st.subheader("📊 Uzturvielu informācija (uz 100g/ml)")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        if product.get('energy_kj'):
            st.metric("Enerģija", f"{product['energy_kj']} kJ")
        if product.get('energy_kcal'):
            st.caption(f"({product['energy_kcal']} kcal)")
    
    with col2:
        if product.get('fat_total') is not None:
            st.metric("Tauki", f"{product['fat_total']}g")
        if product.get('fat_saturated') is not None:
            st.caption(f"t.sk. piesātinātās: {product['fat_saturated']}g")
    
    with col3:
        if product.get('carbs_total') is not None:
            st.metric("Ogļhidrāti", f"{product['carbs_total']}g")
        if product.get('carbs_sugars') is not None:
            st.caption(f"t.sk. cukuri: {product['carbs_sugars']}g")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        if product.get('protein') is not None:
            st.metric("Olbaltumvielas", f"{product['protein']}g")
    
    with col2:
        if product.get('salt') is not None:
            st.metric("Sāls", f"{product['salt']}g")
    
    with col3:
        if product.get('fiber') is not None:
            st.metric("Šķiedrvielas", f"{product['fiber']}g")
    
    # Ingredients
    if product.get('ingredients_text'):
        st.subheader("📝 Sastāvdaļas")
        st.write(product['ingredients_text'])
    
    # Ingredient Analysis with Categories
    try:
        sku = product.get('sku')
        if sku:
            ingredient_query = """
                SELECT 
                    ia.ingredient,
                    COALESCE(ia.clean_name, ia.ingredient) as display_name,
                    COALESCE(ia.category, 'uncategorized') as category,
                    ia.is_processed
                FROM ingredient_product_mapping ipm
                JOIN ingredient_analysis ia ON ipm.ingredient_id = ia.id
                WHERE ipm.product_sku = %s
                ORDER BY ia.category, ia.ingredient
            """
            db._ensure_connection()
            with db.connection.cursor() as cur:
                cur.execute(ingredient_query, (sku,))
                ingredients = cur.fetchall()
            
            if ingredients:
                st.subheader("🧪 Ingredientu analīze")
                
                natural_list = []
                processed_list = []
                uncategorized_list = []
                
                for ing in ingredients:
                    name = ing['display_name'] if ing.get('display_name') else ing['ingredient']
                    category = ing['category'] if ing.get('category') else 'uncategorized'
                    
                    if category == 'natural':
                        natural_list.append(f"🌿 {name}")
                    elif category == 'processed':
                        processed_list.append(f"🏭 {name}")
                    else:
                        uncategorized_list.append(f"❓ {name}")
                
                if natural_list:
                    st.markdown("**Dabiski:** " + ", ".join(natural_list[:10]))
                    if len(natural_list) > 10:
                        st.caption(f"...un vēl {len(natural_list) - 10}")
                
                if processed_list:
                    st.markdown("**Apstrādāti:** " + ", ".join(processed_list[:10]))
                    if len(processed_list) > 10:
                        st.caption(f"...un vēl {len(processed_list) - 10}")
                
                if uncategorized_list:
                    with st.expander(f"Nekategorizēti ({len(uncategorized_list)})"):
                        st.write(", ".join(uncategorized_list))
    except Exception as e:
        st.error(f"Error loading ingredients: {e}")
    
    # Country of Origin
    if product.get('country_of_origin') and product.get('country_of_origin') != 'Unknown':
        st.subheader("🌍 Izcelsmes valsts")
        st.write(product['country_of_origin'])
    
    # Category
    st.subheader("📂 Kategorija")
    st.write(f"{product.get('category_name', 'N/A')} ({product.get('rimi_category_code', 'N/A')})")
    
    # Link to Rimi
    if product.get('rimi_url'):
        st.subheader("🔗 Saites")
        st.markdown(f"[Skatīt Rimi.lv]({product['rimi_url']})")
    
    db.close()


def section_nutrition_enrichment():
    """Section 3: Nutrition Data Enrichment from USDA"""
    from nutrition_enrichment_service import NutritionEnrichmentService, EnrichmentBatch
    
    st.header("🥗 Nutrition Data Enrichment")
    st.caption("Enrich products with missing nutrition data using USDA FoodData Central")
    
    if 'enrichment_batch' not in st.session_state:
        st.session_state.enrichment_batch = None
    if 'enrichment_processing' not in st.session_state:
        st.session_state.enrichment_processing = False
    if 'enrichment_log' not in st.session_state:
        st.session_state.enrichment_log = []
    
    def log_callback(msg):
        st.session_state.enrichment_log.append(msg)
    
    try:
        service = NutritionEnrichmentService(status_callback=log_callback)
        stats = service.get_enrichment_stats()
        
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Needs Enrichment", stats['needs_enrichment'])
        with col2:
            st.metric("Reviewed", stats['reviewed'])
        with col3:
            st.metric("From USDA", stats['from_usda'])
        with col4:
            st.metric("From Rimi", stats['from_rimi'])
        
        st.divider()
        
        col1, col2, col3 = st.columns([1, 1, 2])
        
        with col1:
            batch_size = st.selectbox("Batch Size", [10, 20, 30, 50], index=1)
        
        with col2:
            if st.button("🔄 Load Batch", type="primary", disabled=st.session_state.enrichment_processing):
                st.session_state.enrichment_log = []
                st.session_state.enrichment_processing = True
                st.rerun()
        
        with col3:
            if st.session_state.enrichment_batch:
                batch = st.session_state.enrichment_batch
                st.info(f"Batch: {batch.approved} approved, {batch.skipped} skipped, {batch.pending} pending, {batch.no_match} no match")
            if stats['skipped'] > 0:
                st.caption(f"📋 {stats['skipped']} products in skip list (sorted to end of batches)")
        
        if st.session_state.enrichment_processing and not st.session_state.enrichment_batch:
            with st.spinner("Loading and processing products..."):
                products = service.get_products_needing_enrichment(limit=batch_size)
                if products:
                    batch = service.process_batch(products)
                    st.session_state.enrichment_batch = batch
                else:
                    st.success("No products need enrichment!")
                st.session_state.enrichment_processing = False
                st.rerun()
        
        if st.session_state.enrichment_log:
            with st.expander("Processing Log", expanded=False):
                for log in st.session_state.enrichment_log[-50:]:
                    st.text(log)
        
        if st.session_state.enrichment_batch:
            batch = st.session_state.enrichment_batch
            
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                if st.button("✅ Approve All Matches", disabled=batch.pending == 0):
                    for match in batch.matches:
                        if match.status == 'pending' and match.usda_match:
                            service.save_enrichment(match)
                    st.rerun()
            with col2:
                if st.button("⏭️ Skip All Remaining"):
                    for match in batch.matches:
                        if match.status in ['pending', 'no_match']:
                            service.skip_product(match)
                    st.rerun()
            with col3:
                if st.button("🔄 Reprocess Skipped", disabled=batch.skipped == 0):
                    for match in batch.matches:
                        if match.status == 'skipped':
                            service.unskip_product(match)
                    st.rerun()
            with col4:
                if st.button("🆕 New Batch"):
                    st.session_state.enrichment_batch = None
                    st.session_state.enrichment_log = []
                    st.rerun()
            
            st.divider()
            
            for i, match in enumerate(batch.matches):
                status_icon = {
                    'pending': '⏳',
                    'approved': '✅',
                    'skipped': '⏭️',
                    'no_match': '❌'
                }.get(match.status, '❓')
                
                with st.expander(f"{status_icon} {match.product.name} (SKU: {match.product.sku})", expanded=(match.status == 'pending')):
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        st.markdown("**Product Info:**")
                        st.write(f"**Name:** {match.product.name}")
                        st.write(f"**Category:** {match.product.category_name or 'N/A'}")
                        st.write(f"**Translation:** {match.translation.english}")
                        st.write(f"**Method:** {match.translation.method} ({match.translation.confidence:.0%})")
                    
                    with col2:
                        if match.usda_options:
                            st.markdown("**USDA Match Options:**")
                            
                            option_labels = [
                                f"{opt.description} (Score: {opt.score:.0f})"
                                for opt in match.usda_options
                            ]
                            
                            selected_idx = st.selectbox(
                                "Select match:",
                                options=range(len(option_labels)),
                                format_func=lambda x: option_labels[x],
                                index=match.selected_index,
                                key=f"select_{i}"
                            )
                            
                            if selected_idx != match.selected_index:
                                match.select_option(selected_idx)
                            
                            if match.usda_match:
                                st.write(f"**Data Type:** {match.usda_match.data_type}")
                                usda_url = f"https://fdc.nal.usda.gov/fdc-app.html#/food-details/{match.usda_match.fdc_id}/nutrients"
                                st.markdown(f"**USDA Link:** [FDC #{match.usda_match.fdc_id}]({usda_url})")
                                
                                if match.usda_match.nutrition:
                                    n = match.usda_match.nutrition
                                    st.markdown("**Nutrition (per 100g):**")
                                    ncol1, ncol2, ncol3 = st.columns(3)
                                    with ncol1:
                                        st.metric("Energy", f"{n.energy_kcal or 0:.0f} kcal")
                                        st.metric("Protein", f"{n.protein or 0:.1f}g")
                                    with ncol2:
                                        st.metric("Fat", f"{n.fat_total or 0:.1f}g")
                                        st.metric("Sat. Fat", f"{n.fat_saturated or 0:.1f}g")
                                    with ncol3:
                                        st.metric("Carbs", f"{n.carbs_total or 0:.1f}g")
                                        st.metric("Sugars", f"{n.carbs_sugars or 0:.1f}g")
                                    
                                    scol1, scol2 = st.columns(2)
                                    with scol1:
                                        st.metric("Salt", f"{n.salt or 0:.2f}g")
                                    with scol2:
                                        st.metric("Fiber", f"{n.fiber or 0:.1f}g")
                        else:
                            st.warning("No USDA match found")
                            st.info("Use custom search below to find a match")
                    
                    if match.status in ['pending', 'no_match', 'skipped']:
                        bcol1, bcol2, bcol3 = st.columns(3)
                        
                        with bcol1:
                            if match.usda_match and match.status == 'pending' and st.button("✅ Approve", key=f"approve_{i}"):
                                service.save_enrichment(match)
                                st.rerun()
                        
                        with bcol2:
                            if match.status in ['pending', 'no_match'] and st.button("⏭️ Skip", key=f"skip_{i}"):
                                service.skip_product(match)
                                st.rerun()
                            if match.status == 'skipped' and st.button("🔄 Unskip", key=f"unskip_{i}"):
                                service.unskip_product(match)
                                st.rerun()
                        
                        with bcol3:
                            custom_term = st.text_input("Custom search:", key=f"search_{i}", 
                                placeholder="e.g., pomegranate, lime, persimmon")
                            if custom_term and st.button("🔍 Search", key=f"dosearch_{i}"):
                                new_match = service.search_custom_term(match.product, custom_term)
                                batch.matches[i] = new_match
                                st.rerun()
        
    except Exception as e:
        st.error(f"Error initializing enrichment service: {str(e)}")
        st.info("Make sure USDA_API_KEY is set in secrets.")
        import traceback
        st.code(traceback.format_exc())


def section_change_report():
    """Section 4: Change Report - Compare current vs previous product state"""
    st.header("📊 Change Report")
    
    from change_report import ChangeReportGenerator
    
    try:
        report = ChangeReportGenerator()
        
        timestamps = report.get_update_timestamps()
        if timestamps['current_update']:
            current_str = timestamps['current_update'].strftime("%Y-%m-%d %H:%M")
            previous_str = timestamps['previous_update'].strftime("%Y-%m-%d %H:%M") if timestamps['previous_update'] else "N/A"
            st.caption(f"Comparing: **{current_str}** vs **{previous_str}**")
        
        stats = report.get_summary_stats()
        
        st.subheader("📈 Summary")
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("Total Products", stats.total_products)
        with col2:
            st.metric("New Products", stats.new_products, delta=f"+{stats.new_products}" if stats.new_products > 0 else None)
        with col3:
            st.metric("Price Changes", stats.price_changed)
        with col4:
            st.metric("Availability Changes", stats.availability_changed)
        
        col5, col6, col7, col8 = st.columns(4)
        with col5:
            st.metric("Price Increased", stats.price_increased, delta=f"↑ {stats.price_increased}", delta_color="inverse")
        with col6:
            st.metric("Price Decreased", stats.price_decreased, delta=f"↓ {stats.price_decreased}", delta_color="normal")
        with col7:
            st.metric("Became Available", stats.became_available, delta=f"+{stats.became_available}" if stats.became_available > 0 else None)
        with col8:
            st.metric("Became Unavailable", stats.became_unavailable, delta=f"-{stats.became_unavailable}" if stats.became_unavailable > 0 else None, delta_color="inverse")
        
        st.divider()
        
        tab1, tab2, tab3, tab4 = st.tabs(["💰 Price Changes", "📦 Availability Changes", "🆕 New Products", "📂 By Category"])
        
        with tab1:
            st.subheader("Price Changes")
            st.caption("Prices shown are effective prices (MansRimi discount price when available, otherwise regular price)")
            price_changes = report.get_price_changes(limit=100)
            
            if price_changes:
                import pandas as pd
                df = pd.DataFrame(price_changes)
                df['previous_price'] = df['previous_price'].fillna(0)
                df['current_price'] = df['current_price'].fillna(0)
                df['price_change_pct'] = df['price_change_pct'].fillna(0)
                
                st.write(f"**{stats.price_increased} price increases, {stats.price_decreased} price decreases** (showing top 100 by change magnitude)")
                
                def format_price_with_discount(row, price_col, has_discount_col, regular_price_col, discount_price_col):
                    """Format price with discount indicator if applicable"""
                    price = row[price_col]
                    has_discount = row.get(has_discount_col, False)
                    if has_discount:
                        regular = row.get(regular_price_col, 0) or 0
                        return f"{price:.2f} (was {regular:.2f})"
                    return f"{price:.2f}"
                
                df['previous_display'] = df.apply(
                    lambda r: format_price_with_discount(r, 'previous_price', 'previous_has_discount', 'previous_regular_price', 'previous_discount_price'),
                    axis=1
                )
                df['current_display'] = df.apply(
                    lambda r: format_price_with_discount(r, 'current_price', 'current_has_discount', 'current_regular_price', 'current_discount_price'),
                    axis=1
                )
                
                display_df = df[['name', 'category_name', 'previous_display', 'current_display', 'price_change_pct', 'rimi_url']].copy()
                display_df.columns = ['Product', 'Category', 'Previous (€)', 'Current (€)', 'Change (%)', 'Link']
                st.dataframe(
                    display_df, 
                    use_container_width=True, 
                    hide_index=True,
                    column_config={
                        "Link": st.column_config.LinkColumn(
                            "Rimi",
                            display_text="Open",
                            help="Click to view product on Rimi website"
                        )
                    }
                )
            else:
                st.info("No price changes detected")
        
        with tab2:
            st.subheader("Availability Changes")
            avail_changes = report.get_availability_changes(limit=100)
            
            if avail_changes:
                import pandas as pd
                df = pd.DataFrame(avail_changes)
                df['status_change'] = df.apply(
                    lambda r: "🟢 Now Available" if r['current_available'] else "🔴 Now Unavailable", 
                    axis=1
                )
                
                st.write(f"**{stats.became_available} became available, {stats.became_unavailable} became unavailable** (showing top 100)")
                
                display_df = df[['name', 'category_name', 'status_change', 'current_price']].copy()
                display_df.columns = ['Product', 'Category', 'Status', 'Price (€)']
                st.dataframe(display_df, use_container_width=True, hide_index=True)
            else:
                st.info("No availability changes detected")
        
        with tab3:
            st.subheader("New Products")
            new_products = report.get_new_products(limit=100)
            
            if new_products:
                import pandas as pd
                df = pd.DataFrame(new_products)
                df['status'] = df['is_available'].apply(lambda x: "🟢 Available" if x else "🔴 Unavailable")
                
                display_df = df[['name', 'category_name', 'price', 'status']].copy()
                display_df.columns = ['Product', 'Category', 'Price (€)', 'Status']
                st.dataframe(display_df, use_container_width=True, hide_index=True)
            else:
                st.info("No new products detected")
        
        with tab4:
            st.subheader("Changes by Category")
            category_breakdown = report.get_category_breakdown()
            
            if category_breakdown:
                import pandas as pd
                df = pd.DataFrame(category_breakdown)
                df['total_changes'] = df['new_products'] + df['price_changed'] + df['availability_changed']
                
                display_df = df[['category_name', 'category_code', 'total_products', 'new_products', 'price_changed', 'availability_changed']].copy()
                display_df.columns = ['Category', 'Code', 'Total', 'New', 'Price Δ', 'Avail Δ']
                st.dataframe(display_df, use_container_width=True, hide_index=True)
            else:
                st.info("No category changes detected")
                
    except Exception as e:
        st.error(f"Error generating report: {str(e)}")
        import traceback
        st.code(traceback.format_exc())


def section_nutriscore_recalculation():
    """Section: Nutri-Score Recalculation"""
    st.header("🔄 Nutri-Score Recalculation")
    
    st.info("""
    Recalculate Nutri-Score for products using the updated category mappings.
    This will update the `nutri_score_grade` and `nutri_score_points` in the database.
    """)
    
    from nutriscore_calculator import NutriscoreCalculator, FAT_CATEGORIES, CHEESE_CATEGORIES, FULL_FVN_CATEGORIES, HALF_FVN_CATEGORIES
    
    with st.expander("📋 Current Category Mappings", expanded=False):
        col1, col2 = st.columns(2)
        with col1:
            st.write("**Fat Categories:**")
            for cat in sorted(FAT_CATEGORIES):
                st.caption(cat)
            st.write("**Cheese Categories:**")
            for cat in sorted(CHEESE_CATEGORIES):
                st.caption(cat)
        with col2:
            st.write("**100% Fruits/Veg/Nuts:**")
            for cat in sorted(FULL_FVN_CATEGORIES):
                st.caption(cat)
            st.write("**50% Fruits/Veg/Nuts:**")
            for cat in sorted(HALF_FVN_CATEGORIES):
                st.caption(cat)
    
    mode = st.radio(
        "Recalculation Mode:",
        ["Single Product (by SKU)", "By Category", "All Products"],
        horizontal=True
    )
    
    db = ProductViewDatabase()
    
    if mode == "Single Product (by SKU)":
        sku = st.text_input("Enter Product SKU:")
        
        if st.button("Recalculate Nutri-Score", type="primary") and sku:
            with st.spinner("Recalculating..."):
                result = recalculate_nutriscore_for_product(db, sku.strip())
                if result['success']:
                    details = result.get('details', {})
                    old_grade = details.get('old_grade')
                    new_grade = details.get('new_grade')
                    old_score = details.get('old_score')
                    new_score = details.get('new_score')
                    
                    changed = (old_grade != new_grade) or (str(old_score) != str(new_score))
                    
                    if changed:
                        st.success(f"✅ Score changed: {old_grade} ({old_score}) → {new_grade} ({new_score})")
                    else:
                        st.info(f"ℹ️ No change: {new_grade} ({new_score})")
                    
                    if details:
                        st.json(details)
                else:
                    st.error(f"❌ {result['message']}")
    
    elif mode == "By Category":
        db._ensure_connection()
        with db.connection.cursor() as cur:
            cur.execute("""
                SELECT rimi_category_code, name_lv 
                FROM normalized_categories 
                WHERE level = 2 
                ORDER BY name_lv
            """)
            categories = [dict(row) for row in cur.fetchall()]
        
        category_options = {f"{c['name_lv']} ({c['rimi_category_code']})": c['rimi_category_code'] for c in categories}
        
        selected_category_name = st.selectbox("Select Category:", list(category_options.keys()))
        selected_category_code = category_options.get(selected_category_name)
        
        if st.button("Recalculate Nutri-Score for Category", type="primary") and selected_category_code:
            products = get_products_for_nutriscore_recalc(db, category_code=selected_category_code)
            
            if not products:
                st.warning("No products with nutrition data found in this category.")
            else:
                st.write(f"Found **{len(products)}** products with nutrition data in this category.")
                
                progress_bar = st.progress(0)
                status_text = st.empty()
                results_placeholder = st.empty()
                
                success_count = 0
                changed_count = 0
                failed_count = 0
                skipped_count = 0
                
                for i, product in enumerate(products):
                    status_text.text(f"Processing {i+1}/{len(products)}: {product['name'][:50]}...")
                    result = recalculate_nutriscore_for_product_data(db, product)
                    
                    if result['success']:
                        success_count += 1
                        details = result.get('details', {})
                        old_grade = details.get('old_grade')
                        new_grade = details.get('new_grade')
                        old_score = details.get('old_score')
                        new_score = details.get('new_score')
                        if (old_grade != new_grade) or (str(old_score) != str(new_score)):
                            changed_count += 1
                    elif result.get('skipped'):
                        skipped_count += 1
                    else:
                        failed_count += 1
                    
                    progress_bar.progress((i + 1) / len(products))
                
                status_text.text("Recalculation complete!")
                results_placeholder.success(f"""
                **Results:**
                - ✅ Successfully processed: {success_count}
                - 🔄 Score changed: {changed_count}
                - ⏭️ Skipped (no nutrition data): {skipped_count}
                - ❌ Failed: {failed_count}
                """)
    
    else:  # All Products
        products = get_products_for_nutriscore_recalc(db)
        st.write(f"Found **{len(products)}** products with nutrition data.")
        
        st.warning("⚠️ This will recalculate Nutri-Score for all products. This may take several minutes.")
        
        if st.button("Recalculate All Nutri-Scores", type="primary"):
            progress_bar = st.progress(0)
            status_text = st.empty()
            results_placeholder = st.empty()
            
            success_count = 0
            changed_count = 0
            failed_count = 0
            skipped_count = 0
            
            for i, product in enumerate(products):
                status_text.text(f"Processing {i+1}/{len(products)}: {product['sku']} - {product['name'][:40]}...")
                result = recalculate_nutriscore_for_product_data(db, product)
                
                if result['success']:
                    success_count += 1
                    details = result.get('details', {})
                    old_grade = details.get('old_grade')
                    new_grade = details.get('new_grade')
                    old_score = details.get('old_score')
                    new_score = details.get('new_score')
                    if (old_grade != new_grade) or (str(old_score) != str(new_score)):
                        changed_count += 1
                elif result.get('skipped'):
                    skipped_count += 1
                else:
                    failed_count += 1
                
                progress_bar.progress((i + 1) / len(products))
            
            status_text.text("Recalculation complete!")
            results_placeholder.success(f"""
            **Results:**
            - ✅ Successfully processed: {success_count}
            - 🔄 Score changed: {changed_count}
            - ⏭️ Skipped (no nutrition data): {skipped_count}
            - ❌ Failed: {failed_count}
            """)


def get_products_for_nutriscore_recalc(db: ProductViewDatabase, category_code: str = None):
    """Get products with nutrition data for recalculation."""
    query = """
        SELECT 
            p.product_id,
            p.sku,
            p.name,
            nc.rimi_category_code as category_code,
            nf.energy_kj,
            nf.carbs_sugars as sugars,
            nf.fat_saturated as saturated_fat,
            nf.salt,
            nf.protein,
            nf.fiber,
            nf.nutri_score_grade as current_grade,
            nf.nutri_score_points as current_score
        FROM products p
        JOIN nutritionfacts nf ON p.product_id = nf.product_id
        LEFT JOIN normalized_categories nc ON p.category_id = nc.category_id
        WHERE nf.energy_kj IS NOT NULL
          AND nf.carbs_sugars IS NOT NULL
          AND nf.fat_saturated IS NOT NULL
          AND nf.salt IS NOT NULL
          AND nf.protein IS NOT NULL
    """
    
    params = []
    if category_code:
        query += " AND nc.rimi_category_code LIKE %s"
        params.append(f"{category_code}%")
    
    query += " ORDER BY p.sku"
    
    db._ensure_connection()
    with db.connection.cursor() as cur:
        cur.execute(query, params if params else None)
        return [dict(row) for row in cur.fetchall()]


def recalculate_nutriscore_for_product(db: ProductViewDatabase, sku: str):
    """Recalculate Nutri-Score for a single product by SKU."""
    query = """
        SELECT 
            p.product_id,
            p.sku,
            p.name,
            nc.rimi_category_code as category_code,
            nf.energy_kj,
            nf.carbs_sugars as sugars,
            nf.fat_saturated as saturated_fat,
            nf.salt,
            nf.protein,
            nf.fiber,
            nf.nutri_score_grade as current_grade,
            nf.nutri_score_points as current_score
        FROM products p
        LEFT JOIN nutritionfacts nf ON p.product_id = nf.product_id
        LEFT JOIN normalized_categories nc ON p.category_id = nc.category_id
        WHERE p.sku = %s
    """
    
    db._ensure_connection()
    with db.connection.cursor() as cur:
        cur.execute(query, (sku,))
        row = cur.fetchone()
        
        if not row:
            return {'success': False, 'message': f'Product with SKU {sku} not found'}
        
        product = dict(row)
        return recalculate_nutriscore_for_product_data(db, product)


def recalculate_nutriscore_for_product_data(db: ProductViewDatabase, product: dict):
    """Recalculate Nutri-Score for a product using its data."""
    from nutriscore_calculator import NutriscoreCalculator
    
    required_fields = ['energy_kj', 'sugars', 'saturated_fat', 'salt', 'protein']
    for field in required_fields:
        if product.get(field) is None:
            return {'success': False, 'skipped': True, 'message': f'Missing required field: {field}'}
    
    calculator = NutriscoreCalculator()
    
    try:
        fiber_value = product.get('fiber')
        fiber_float = float(fiber_value) if fiber_value is not None else 0.0
        
        result = calculator.calculate_single_product(
            energy_kj=float(product['energy_kj']),
            sugars=float(product['sugars']),
            saturated_fat=float(product['saturated_fat']),
            salt=float(product['salt']),
            protein=float(product['protein']),
            fiber=fiber_float,
            category_code=product.get('category_code')
        )
        
        if result['success']:
            new_grade = result['grade']
            new_score = result['score']
            
            update_query = """
                UPDATE nutritionfacts 
                SET nutri_score_grade = %s, nutri_score_points = %s
                WHERE product_id = %s
            """
            
            db._ensure_connection()
            with db.connection.cursor() as cur:
                cur.execute(update_query, (new_grade, new_score, product['product_id']))
                db.connection.commit()
            
            old_grade = product.get('current_grade', 'N/A')
            old_score = product.get('current_score', 'N/A')
            
            return {
                'success': True,
                'message': f"Updated {product['sku']}: {old_grade} ({old_score}) → {new_grade} ({new_score})",
                'details': {
                    'sku': product['sku'],
                    'name': product['name'],
                    'category_code': product.get('category_code'),
                    'old_grade': old_grade,
                    'old_score': old_score,
                    'new_grade': new_grade,
                    'new_score': new_score,
                    'classification': result.get('classification', {})
                }
            }
        else:
            return {'success': False, 'message': result.get('error', 'Calculation failed')}
            
    except Exception as e:
        return {'success': False, 'message': str(e)}


def section_ingredient_import():
    """Section: AI-Powered Ingredient Categorization"""
    from ingredient_ai_categorizer import get_categorization_stats, backfill_uncategorized_ingredients
    
    st.header("🧪 AI Ingredient Categorization")
    
    stats = get_categorization_stats()
    
    if stats:
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total Ingredients", stats['total'])
        with col2:
            st.metric("Natural", stats['natural'])
        with col3:
            st.metric("Processed", stats['processed'])
        with col4:
            uncategorized_pct = round((stats['uncategorized'] / stats['total']) * 100, 1) if stats['total'] > 0 else 0
            st.metric("Uncategorized", f"{stats['uncategorized']} ({uncategorized_pct}%)")
        
        categorized = stats['natural'] + stats['processed']
        coverage = round((categorized / stats['total']) * 100, 1) if stats['total'] > 0 else 0
        st.progress(coverage / 100, f"Coverage: {coverage}% ({categorized}/{stats['total']})")
    else:
        st.error("Could not load ingredient statistics")
        return
    
    st.divider()
    
    st.subheader("AI Backfill")
    st.markdown("""
    Use Google AI (Gemini) to automatically categorize uncategorized ingredients.
    - **Natural**: Whole foods, unprocessed (fruits, vegetables, meat, herbs, etc.)
    - **Processed**: Industrial/refined (E-numbers, preservatives, modified starches, etc.)
    """)
    
    if 'backfill_running' not in st.session_state:
        st.session_state.backfill_running = False
    if 'backfill_progress' not in st.session_state:
        st.session_state.backfill_progress = 0
    if 'backfill_results' not in st.session_state:
        st.session_state.backfill_results = None
    
    col1, col2 = st.columns(2)
    with col1:
        batch_size = st.number_input("Batch size (ingredients per AI call)", min_value=10, max_value=100, value=50)
    with col2:
        limit = st.number_input("Max ingredients to process (0 = all)", min_value=0, max_value=10000, value=0)
    
    estimated_calls = (stats['uncategorized'] // batch_size) + 1 if stats['uncategorized'] > 0 else 0
    st.caption(f"Estimated API calls: ~{estimated_calls} (at {batch_size} ingredients/call)")
    
    if stats['uncategorized'] == 0:
        st.success("All ingredients are categorized!")
    elif st.button("Start AI Categorization", type="primary", disabled=st.session_state.backfill_running):
        st.session_state.backfill_running = True
        st.session_state.backfill_progress = 0
        
        progress_bar = st.progress(0, "Starting...")
        status_text = st.empty()
        results_container = st.container()
        
        def progress_callback(processed, total, current_batch):
            pct = processed / total if total > 0 else 0
            progress_bar.progress(pct, f"Processing: {processed}/{total}")
            
            if current_batch:
                natural_in_batch = sum(1 for r in current_batch if r['category'] == 'natural')
                processed_in_batch = sum(1 for r in current_batch if r['category'] == 'processed')
                status_text.caption(f"Last batch: {natural_in_batch} natural, {processed_in_batch} processed")
        
        try:
            limit_value = limit if limit > 0 else None
            results = backfill_uncategorized_ingredients(
                batch_size=batch_size,
                limit=limit_value,
                progress_callback=progress_callback
            )
            
            st.session_state.backfill_results = results
            st.session_state.backfill_running = False
            
            with results_container:
                st.success(f"Categorization complete!")
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("Processed", results['processed'])
                with col2:
                    st.metric("Natural", results['natural'])
                with col3:
                    st.metric("Processed", results['processed_count'])
                with col4:
                    st.metric("Failed", results['failed'])
            
            st.rerun()
            
        except Exception as e:
            st.session_state.backfill_running = False
            st.error(f"Error during categorization: {str(e)}")
    
    if st.session_state.backfill_results and not st.session_state.backfill_running:
        results = st.session_state.backfill_results
        st.info(f"Last run: {results['processed']} processed, {results['natural']} natural, {results['processed_count']} processed, {results['failed']} failed")
    
    st.divider()
    
    st.subheader("Recent Categorizations")
    
    db = ProductViewDatabase()
    db._ensure_connection()
    
    with db.connection.cursor() as cur:
        cur.execute("""
            SELECT id, ingredient, clean_name, category, is_processed, frequency
            FROM ingredient_analysis
            WHERE category != 'uncategorized' AND category IS NOT NULL
            ORDER BY id DESC
            LIMIT 20
        """)
        recent = cur.fetchall()
    
    if recent:
        for ing in recent:
            emoji = "🌿" if ing['category'] == 'natural' else "🏭" if ing['category'] == 'processed' else "❓"
            clean = ing['clean_name'] if ing['clean_name'] else ing['ingredient']
            st.markdown(f"{emoji} **{clean}** ← _{ing['ingredient']}_ (freq: {ing['frequency']})")
    else:
        st.info("No categorized ingredients yet. Run the AI backfill above to start.")
    
    st.divider()
    section_suspicion_analysis()


def section_suspicion_analysis():
    """Section: NOVA4 Suspicion Analysis for processed ingredients"""
    from suspicion_analyzer import get_suspicion_stats, run_suspicion_analysis, reset_suspicion_analysis
    
    st.header("⚠️ NOVA4 Suspicion Analysis")
    st.markdown("""
    Analyze **processed ingredients** to identify NOVA4 ultra-processed food markers.
    Based on EU/Latvia food safety guidelines and EFSA regulations.
    """)
    
    suspicion_stats = get_suspicion_stats()
    
    if suspicion_stats:
        col1, col2, col3, col4, col5, col6 = st.columns(6)
        with col1:
            st.metric("Total Processed", suspicion_stats['total_processed'])
        with col2:
            st.metric("🔴 Avoid", suspicion_stats['avoid_count'])
        with col3:
            st.metric("🟠 Limit", suspicion_stats['limit_count'])
        with col4:
            st.metric("🟡 Caution", suspicion_stats['caution_count'])
        with col5:
            st.metric("✅ Clean", suspicion_stats.get('clean_count', 0))
        with col6:
            analyzed_pct = round((suspicion_stats['analyzed'] / suspicion_stats['total_processed']) * 100, 1) if suspicion_stats['total_processed'] > 0 else 0
            st.metric("Analyzed", f"{suspicion_stats['analyzed']} ({analyzed_pct}%)")
        
        if suspicion_stats['total_processed'] > 0:
            progress_val = suspicion_stats['analyzed'] / suspicion_stats['total_processed']
            st.progress(progress_val, f"Analysis Progress: {suspicion_stats['analyzed']}/{suspicion_stats['total_processed']}")
    else:
        st.error("Could not load suspicion statistics")
        return
    
    st.divider()
    
    st.subheader("Run Suspicion Analysis")
    st.markdown("""
    Uses AI to match processed ingredients against the NOVA4 suspicious additives list:
    - **🔴 Avoid**: Strong evidence of harm (Southampton Six dyes, nitrites, trans fats)
    - **🟠 Limit**: Regular consumption may have negative effects (MSG, sweeteners)
    - **🟡 Caution**: Industrial marker, minimal direct harm (emulsifiers, fillers)
    """)
    
    if 'suspicion_running' not in st.session_state:
        st.session_state.suspicion_running = False
    if 'suspicion_results' not in st.session_state:
        st.session_state.suspicion_results = None
    
    col1, col2 = st.columns(2)
    with col1:
        susp_batch_size = st.number_input("Batch size", min_value=10, max_value=100, value=50, key="susp_batch")
    with col2:
        susp_limit = st.number_input("Max to process (0 = all)", min_value=0, max_value=10000, value=0, key="susp_limit")
    
    unanalyzed = suspicion_stats['unanalyzed'] if suspicion_stats else 0
    estimated_calls = (unanalyzed // susp_batch_size) + 1 if unanalyzed > 0 else 0
    st.caption(f"Unanalyzed: {unanalyzed} | Estimated API calls: ~{estimated_calls}")
    
    col_btn1, col_btn2 = st.columns(2)
    
    with col_btn1:
        if unanalyzed == 0:
            st.success("All processed ingredients analyzed!")
        elif st.button("Start Suspicion Analysis", type="primary", disabled=st.session_state.suspicion_running):
            st.session_state.suspicion_running = True
            
            progress_bar = st.progress(0, "Starting analysis...")
            status_text = st.empty()
            results_container = st.container()
            
            def susp_progress_callback(processed, total, current_batch):
                pct = processed / total if total > 0 else 0
                progress_bar.progress(pct, f"Analyzing: {processed}/{total}")
                
                if current_batch:
                    avoid_in_batch = sum(1 for r in current_batch if r.get('suspicion_level') == 'avoid')
                    limit_in_batch = sum(1 for r in current_batch if r.get('suspicion_level') == 'limit')
                    caution_in_batch = sum(1 for r in current_batch if r.get('suspicion_level') == 'caution')
                    status_text.caption(f"Last batch: {avoid_in_batch} avoid, {limit_in_batch} limit, {caution_in_batch} caution")
            
            try:
                limit_value = susp_limit if susp_limit > 0 else None
                results = run_suspicion_analysis(
                    batch_size=susp_batch_size,
                    limit=limit_value,
                    progress_callback=susp_progress_callback
                )
                
                st.session_state.suspicion_results = results
                st.session_state.suspicion_running = False
                
                with results_container:
                    st.success("Analysis complete!")
                    col1, col2, col3, col4, col5 = st.columns(5)
                    with col1:
                        st.metric("Processed", results['processed'])
                    with col2:
                        st.metric("🔴 Avoid", results['avoid'])
                    with col3:
                        st.metric("🟠 Limit", results['limit_count'])
                    with col4:
                        st.metric("🟡 Caution", results['caution'])
                    with col5:
                        st.metric("Clean", results['clean'])
                
                st.rerun()
                
            except Exception as e:
                st.session_state.suspicion_running = False
                st.error(f"Error during analysis: {str(e)}")
    
    with col_btn2:
        if st.button("🔄 Reset Analysis", type="secondary"):
            reset_suspicion_analysis()
            st.success("Suspicion data reset. You can re-run the analysis.")
            st.rerun()
    
    if st.session_state.suspicion_results and not st.session_state.suspicion_running:
        results = st.session_state.suspicion_results
        st.info(f"Last run: {results['processed']} analyzed | 🔴 {results['avoid']} avoid | 🟠 {results['limit_count']} limit | 🟡 {results['caution']} caution | ✅ {results['clean']} clean")
    
    st.divider()
    
    st.subheader("Suspicious Ingredients Found")
    
    db = ProductViewDatabase()
    db._ensure_connection()
    
    with db.connection.cursor() as cur:
        cur.execute("""
            SELECT id, ingredient, clean_name, suspicion_level, suspicion_category, health_note, frequency
            FROM ingredient_analysis
            WHERE suspicion_level IS NOT NULL
            ORDER BY 
                CASE suspicion_level 
                    WHEN 'avoid' THEN 1 
                    WHEN 'limit' THEN 2 
                    WHEN 'caution' THEN 3 
                END,
                frequency DESC
            LIMIT 30
        """)
        suspicious = cur.fetchall()
    
    if suspicious:
        for ing in suspicious:
            level = ing['suspicion_level']
            emoji = "🔴" if level == 'avoid' else "🟠" if level == 'limit' else "🟡"
            clean = ing['clean_name'] if ing['clean_name'] else ing['ingredient']
            cat = ing['suspicion_category'] or "unknown"
            note = ing['health_note'] or ""
            
            level_upper = level.upper() if level else "?"
            st.markdown(f"{emoji} **{level_upper}** | **{clean}** ({cat}) - {note} _(freq: {ing['frequency']})_")
    else:
        st.info("No suspicious ingredients found yet. Run the analysis above to start.")


def main():
    st.title("🛒 Rimi Product Scraper")
    
    col1, col2, col3, col4, col5, col6 = st.columns(6)
    
    with col1:
        if st.button("📦 Categories", use_container_width=True, 
                     type="primary" if st.session_state.view_mode == 'category_processing' else "secondary"):
            st.session_state.view_mode = 'category_processing'
            st.rerun()
    
    with col2:
        if st.button("🛍️ Products", use_container_width=True,
                     type="primary" if st.session_state.view_mode == 'product_view' else "secondary"):
            st.session_state.view_mode = 'product_view'
            st.rerun()
    
    with col3:
        if st.button("🥗 Nutrition", use_container_width=True,
                     type="primary" if st.session_state.view_mode == 'nutrition_enrichment' else "secondary"):
            st.session_state.view_mode = 'nutrition_enrichment'
            st.rerun()
    
    with col4:
        if st.button("📊 Changes", use_container_width=True,
                     type="primary" if st.session_state.view_mode == 'change_report' else "secondary"):
            st.session_state.view_mode = 'change_report'
            st.rerun()
    
    with col5:
        if st.button("🔄 Nutri-Score", use_container_width=True,
                     type="primary" if st.session_state.view_mode == 'nutriscore_recalc' else "secondary"):
            st.session_state.view_mode = 'nutriscore_recalc'
            st.rerun()
    
    with col6:
        if st.button("🧪 Ingredients", use_container_width=True,
                     type="primary" if st.session_state.view_mode == 'ingredient_import' else "secondary"):
            st.session_state.view_mode = 'ingredient_import'
            st.rerun()
    
    st.divider()
    
    if st.session_state.view_mode == 'category_processing':
        section_category_processing()
    elif st.session_state.view_mode == 'product_view':
        section_product_view()
    elif st.session_state.view_mode == 'change_report':
        section_change_report()
    elif st.session_state.view_mode == 'nutriscore_recalc':
        section_nutriscore_recalculation()
    elif st.session_state.view_mode == 'ingredient_import':
        section_ingredient_import()
    else:
        section_nutrition_enrichment()


if __name__ == "__main__":
    main()
