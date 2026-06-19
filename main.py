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


def render_nova_badge(nova_score: int, explicit: bool = True) -> str:
    """Render a coloured NOVA score badge as HTML."""
    if not nova_score:
        return ""
    colors = {1: '#038141', 2: '#85BB2F', 3: '#EE8100', 4: '#E63E11'}
    color = colors.get(nova_score, '#999')
    opacity = "1.0" if explicit else "0.6"
    return (
        f'<span style="background-color:{color};color:white;font-weight:bold;'
        f'padding:2px 7px;border-radius:3px;font-size:12px;opacity:{opacity}">'
        f'NOVA {nova_score}</span>'
    )


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


def _job_queue_section():
    """Job Queue inner content (called from section_category_processing tab)."""
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


def section_nova_categories():
    """NOVA Classification tab — manually assign NOVA 1–4 to each category."""
    st.subheader("🔢 NOVA Category Classification")

    with st.expander("ℹ️ NOVA classification guide", expanded=False):
        st.markdown("""
| Score | Group | Typical examples |
|---|---|---|
| **NOVA 1** | Unprocessed / minimally processed | Fresh fruit & veg, raw meat & fish, plain milk, eggs, plain nuts |
| **NOVA 2** | Processed culinary ingredients | Oils, butter, flour, sugar, salt, honey, plain vinegar |
| **NOVA 3** | Processed foods | Canned veg, salted nuts, smoked/cured meat, fresh cheese |
| **NOVA 4** | Ultra-processed | Soft drinks, chips, instant noodles, cereals with sugar, sausages, ice cream |

**Setting a Level 1 category** automatically fills in that NOVA value for all children that have not been manually overridden (🔒).
Children you override explicitly stay fixed until you click **Clear**.
        """)

    db = ProductViewDatabase()
    try:
        stats = db.get_nova_stats()
        total = stats['total'] or 1
        pct = round(100 * stats['tagged'] / total)

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total Categories", stats['total'])
        c2.metric("Tagged", stats['tagged'])
        c3.metric("Untagged", stats['untagged'])
        c4.metric("Progress", f"{pct}%")

        st.divider()

        cats = db.get_categories_with_nova()
        cat_map = {c['category_id']: c for c in cats}
        for c in cat_map.values():
            c['_children'] = []
        for c in cats:
            pid = c.get('parent_category_id')
            if pid and pid in cat_map:
                cat_map[pid]['_children'].append(c)

        root_cats = sorted(
            [c for c in cats if not c.get('parent_category_id')],
            key=lambda x: x.get('rimi_category_code') or ''
        )

        nova_opts = [
            "— (unset)",
            "1 · Unprocessed",
            "2 · Culinary ingredients",
            "3 · Processed",
            "4 · Ultra-processed",
        ]

        def render_row(cat, is_level1: bool, depth: int = 0):
            cat_id = cat['category_id']
            nova = cat['nova_score']
            explicit = cat['nova_score_explicit']

            col_name, col_badge, col_sel, col_set, col_clr = st.columns([5, 1, 2, 1, 1])

            with col_name:
                lock_sym = " 🔒" if explicit and not is_level1 else ""
                inh_html = " <em style='color:#888;font-size:0.85em'>(inherited)</em>" if nova and not explicit else ""
                name = cat['name_lv']

                if is_level1:
                    st.markdown(f"**{name}**")
                elif depth == 1:
                    # Level-2: bold, dark left border
                    st.markdown(
                        f'<div style="padding-left:10px;border-left:3px solid #888;margin:2px 0">'
                        f'<strong>{name}</strong>{lock_sym}{inh_html}</div>',
                        unsafe_allow_html=True
                    )
                else:
                    # Level-3+: lighter, progressively indented
                    pad = 10 + (depth - 1) * 20
                    st.markdown(
                        f'<div style="padding-left:{pad}px;border-left:2px solid #ccc;margin:2px 0;font-size:0.92em;color:#333">'
                        f'{name}{lock_sym}{inh_html}</div>',
                        unsafe_allow_html=True
                    )

            with col_badge:
                if nova:
                    st.markdown(render_nova_badge(nova, explicit), unsafe_allow_html=True)
                else:
                    st.caption("—")

            with col_sel:
                default_idx = nova if nova else 0
                st.selectbox(
                    "NOVA score", nova_opts,
                    index=default_idx,
                    key=f"nova_sel_{cat_id}",
                    label_visibility="collapsed"
                )

            with col_set:
                btn_type = "primary" if is_level1 else "secondary"
                if st.button("Set", key=f"nova_set_{cat_id}", type=btn_type, use_container_width=True):
                    sel = st.session_state.get(f"nova_sel_{cat_id}", nova_opts[0])
                    if sel == nova_opts[0]:
                        st.toast("⚠️ Select a NOVA value first.")
                    else:
                        nv = int(sel[0])
                        db.set_category_nova(cat_id, nv)
                        n = db.cascade_nova_to_children(cat_id, nv)
                        if n:
                            st.toast(f"✅ NOVA {nv} set (cascaded to {n} children).")
                        else:
                            st.toast(f"✅ NOVA {nv} set.")
                        st.rerun()

            with col_clr:
                if explicit:
                    if st.button("Clear", key=f"nova_clr_{cat_id}", use_container_width=True):
                        db.clear_category_nova_override(cat_id)
                        st.rerun()

        def render_children(children, depth: int):
            for child in sorted(children, key=lambda x: x.get('rimi_category_code') or ''):
                render_row(child, is_level1=False, depth=depth)
                if child['_children']:
                    render_children(child['_children'], depth + 1)

        for root in root_cats:
            root_nova = root['nova_score']
            nova_label = f"NOVA {root_nova}" if root_nova else "—"
            exp_label = f"[{nova_label}]  {root['name_lv']}  ({root.get('rimi_category_code', '')})"

            with st.expander(exp_label, expanded=False):
                render_row(root, is_level1=True, depth=0)
                if root['_children']:
                    st.divider()
                    render_children(root['_children'], depth=1)

    except Exception as e:
        st.error(f"Error loading NOVA categories: {e}")
        import traceback
        with st.expander("Details"):
            st.code(traceback.format_exc())
    finally:
        db.close()


def section_category_processing():
    """Section 1: Category Processing"""
    st.header("📦 Category Processing")

    tab_queue, tab_nova = st.tabs(["📥 Job Queue", "🔢 NOVA Classification"])

    with tab_nova:
        section_nova_categories()

    with tab_queue:
        _job_queue_section()


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
        st.subheader("🔍 Ātrā meklēšana")
        product_id_input = st.text_input("Product ID", placeholder="Ievadiet produkta ID", label_visibility="collapsed")
        if product_id_input:
            try:
                product_id = int(product_id_input.strip())
                st.session_state.selected_product_id = product_id
                st.rerun()
            except ValueError:
                st.error("Nederīgs ID formāts")
        
        st.divider()
        
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


def render_nutrition_edit_form(db: 'ProductViewDatabase', product: dict):
    """Render inline nutrition edit form with Nutri-Score recalculation"""
    from nutriscore_calculator import NutriscoreCalculator
    
    product_id = product['product_id']
    form_key = f"nutrition_edit_{product_id}"
    
    with st.form(key=form_key):
        st.markdown("**Uzturvielu dati uz 100g/ml:**")
        
        col1, col2 = st.columns(2)
        
        with col1:
            energy_kj = st.number_input(
                "Enerģija (kJ)", 
                value=float(product.get('energy_kj') or 0),
                min_value=0.0,
                step=1.0,
                key=f"energy_kj_{product_id}"
            )
            energy_kcal = st.number_input(
                "Enerģija (kcal)", 
                value=float(product.get('energy_kcal') or 0),
                min_value=0.0,
                step=1.0,
                key=f"energy_kcal_{product_id}"
            )
            fat_total = st.number_input(
                "Tauki (g)", 
                value=float(product.get('fat_total') or 0),
                min_value=0.0,
                step=0.1,
                key=f"fat_total_{product_id}"
            )
            fat_saturated = st.number_input(
                "Piesātinātie tauki (g)", 
                value=float(product.get('fat_saturated') or 0),
                min_value=0.0,
                step=0.1,
                key=f"fat_saturated_{product_id}"
            )
        
        with col2:
            carbs_total = st.number_input(
                "Ogļhidrāti (g)", 
                value=float(product.get('carbs_total') or 0),
                min_value=0.0,
                step=0.1,
                key=f"carbs_total_{product_id}"
            )
            carbs_sugars = st.number_input(
                "Cukuri (g)", 
                value=float(product.get('carbs_sugars') or 0),
                min_value=0.0,
                step=0.1,
                key=f"carbs_sugars_{product_id}"
            )
            fiber = st.number_input(
                "Šķiedrvielas (g)", 
                value=float(product.get('fiber') or 0),
                min_value=0.0,
                step=0.1,
                key=f"fiber_{product_id}"
            )
            protein = st.number_input(
                "Olbaltumvielas (g)", 
                value=float(product.get('protein') or 0),
                min_value=0.0,
                step=0.1,
                key=f"protein_{product_id}"
            )
        
        salt = st.number_input(
            "Sāls (g)", 
            value=float(product.get('salt') or 0),
            min_value=0.0,
            step=0.01,
            key=f"salt_{product_id}"
        )
        
        manual_edit = st.checkbox(
            "Atzīmēt kā manuāli rediģētu (novērsīs automātisko pārrakstīšanu)",
            value=bool(product.get('nutrition_manual_edit')),
            key=f"manual_edit_{product_id}"
        )
        
        submitted = st.form_submit_button("💾 Saglabāt un pārrēķināt Nutri-Score", type="primary")
        
        if submitted:
            try:
                calculator = NutriscoreCalculator()
                nutri_result = calculator.calculate_single_product(
                    energy_kj=energy_kj,
                    sugars=carbs_sugars,
                    saturated_fat=fat_saturated,
                    salt=salt,
                    protein=protein,
                    fiber=fiber,
                    category_code=product.get('rimi_category_code'),
                    product_name=product.get('name'),
                    ingredients_text=product.get('ingredients_text')
                )
                
                new_grade = nutri_result.get('grade') if nutri_result.get('success') else product.get('nutri_score_grade')
                new_score = nutri_result.get('score') if nutri_result.get('success') else product.get('nutri_score_points')
                
                update_query = """
                    UPDATE nutritionfacts 
                    SET energy_kj = %s,
                        energy_kcal = %s,
                        fat_total = %s,
                        fat_saturated = %s,
                        carbs_total = %s,
                        carbs_sugars = %s,
                        fiber = %s,
                        protein = %s,
                        salt = %s,
                        nutri_score_grade = %s,
                        nutri_score_points = %s,
                        nutrition_manual_edit = %s,
                        is_fiber_correct = %s
                    WHERE product_id = %s
                """
                
                db._ensure_connection()
                with db.connection.cursor() as cur:
                    cur.execute(update_query, (
                        int(energy_kj) if energy_kj else None,
                        int(energy_kcal) if energy_kcal else None,
                        fat_total,
                        fat_saturated,
                        carbs_total,
                        carbs_sugars,
                        fiber,
                        protein,
                        salt,
                        new_grade,
                        new_score,
                        manual_edit,
                        True if fiber and fiber > 0 else False,  # Mark fiber as correct when manually edited
                        product_id
                    ))
                    db.connection.commit()
                
                old_grade = product.get('nutri_score_grade', 'N/A')
                st.success(f"Saglabāts! Nutri-Score: {old_grade} → {new_grade} ({new_score} punkti)")
                st.rerun()
                
            except Exception as e:
                st.error(f"Kļūda saglabājot: {str(e)}")


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
    
    if product.get('nutrition_manual_edit'):
        st.info("✏️ Šis produkts ir manuāli rediģēts - uzturvielu dati netiks pārrakstīti")
    
    with st.expander("✏️ Rediģēt uzturvielu informāciju"):
        render_nutrition_edit_form(db, product)
    
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


def section_backfill_quantities():
    """Section: Backfill quantity_value/quantity_unit for NxM multiplier products."""
    st.header("📦 Backfill Quantities")
    st.info(
        "Fixes products whose names contain a multiplier pattern (e.g. **25x2g**, **6x0.33l**) "
        "but whose `quantity_value` stores only the unit size instead of the total. "
        "Example: *Melnā tēja Ahmad Tea Earl Grey 25x2g* → corrects from 2 g to 50 g."
    )

    import re
    from decimal import Decimal

    db = ProductViewDatabase()
    db._ensure_connection()

    def _parse_multiplier(name: str):
        pattern = r'(\d+)\s*[xX×]\s*(\d+(?:[.,]\d+)?)\s*(g|kg|ml|l)\b'
        m = re.search(pattern, name.lower())
        if m:
            try:
                return Decimal(m.group(1)) * Decimal(m.group(2).replace(',', '.')), m.group(3).lower()
            except Exception:
                pass
        return None, None

    with db.connection.cursor() as cur:
        cur.execute(
            "SELECT product_id, sku, name, quantity_value, quantity_unit "
            "FROM products WHERE name ~ '[0-9]+[xX][0-9]' ORDER BY name"
        )
        rows = [dict(zip([d[0] for d in cur.description], r)) for r in cur.fetchall()]

    affected = []
    for row in rows:
        new_val, new_unit = _parse_multiplier(row['name'])
        if new_val is None:
            continue
        old_val = row['quantity_value']
        old_unit = row['quantity_unit']
        if old_val != new_val or old_unit != new_unit:
            affected.append({**row, 'new_val': new_val, 'new_unit': new_unit,
                              'old_val': old_val, 'old_unit': old_unit})

    if not affected:
        st.success(f"✅ All {len(rows)} products with multiplier patterns already have correct quantities. Nothing to fix.")
        return

    st.write(f"Found **{len(affected)}** products needing correction (out of {len(rows)} with multiplier patterns):")

    import pandas as pd
    preview_df = pd.DataFrame([
        {
            'SKU': r['sku'],
            'Name': r['name'][:60],
            'Current': f"{r['old_val']} {r['old_unit']}",
            'Correct': f"{r['new_val']} {r['new_unit']}",
        }
        for r in affected
    ])
    st.dataframe(preview_df, use_container_width=True, hide_index=True)

    st.warning("⚠️ This will update the database. The change is non-destructive — it only corrects the total quantity.")

    if st.button("Run Quantity Backfill", type="primary"):
        progress_bar = st.progress(0)
        status_text = st.empty()
        updated = 0
        errors = 0

        with db.connection.cursor() as cur:
            for i, row in enumerate(affected):
                try:
                    cur.execute(
                        "UPDATE products SET quantity_value = %s, quantity_unit = %s WHERE product_id = %s",
                        (row['new_val'], row['new_unit'], row['product_id'])
                    )
                    updated += 1
                except Exception as e:
                    errors += 1
                    status_text.text(f"Error on {row['sku']}: {e}")
                progress_bar.progress((i + 1) / len(affected))

        if errors == 0:
            db.connection.commit()
            status_text.text("Done!")
            st.success(f"✅ Successfully updated {updated} products with correct quantities.")
        else:
            db.connection.rollback()
            st.error(f"❌ Encountered {errors} errors — rolled back all changes. No data was modified.")


def section_nutriscore_recalculation():
    """Section: Nutri-Score Recalculation"""
    st.header("🔄 Nutri-Score Tools")
    
    sub_tab = st.radio(
        "Tool:",
        ["🔄 Recalculate Nutri-Score", "🌾 Fiber Estimation", "📦 Backfill Quantities"],
        horizontal=True
    )

    if sub_tab == "🌾 Fiber Estimation":
        section_fiber_estimation()
        return

    if sub_tab == "📦 Backfill Quantities":
        section_backfill_quantities()
        return
    
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
            nf.ingredients_text,
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
            nf.ingredients_text,
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
            category_code=product.get('category_code'),
            product_name=product.get('name'),
            ingredients_text=product.get('ingredients_text')
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


def section_fiber_estimation():
    """Section: Fiber Estimation for Nutri-Score Improvement"""
    from fiber_estimator import estimate_fiber, CATEGORY_FIBER_DEFAULTS, EXCEPTION_RULES
    from nutriscore_calculator import NutriscoreCalculator
    
    st.header("🌾 Fiber Estimation")
    st.info("""
    Estimate fiber content for products missing fiber data to improve Nutri-Score accuracy.
    - Uses category defaults from AI analysis of typical fiber content
    - Exception rules override defaults for specific product types (whole grain, dark chocolate, etc.)
    - Products with existing fiber > 0 are skipped
    - Estimated fiber is marked `is_fiber_correct=FALSE` until manually verified
    """)
    
    db = ProductViewDatabase()
    db._ensure_connection()
    
    with db.connection.cursor() as cur:
        cur.execute("""
            SELECT 
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE nf.fiber IS NULL OR nf.fiber = 0) as missing_fiber,
                COUNT(*) FILTER (WHERE nf.fiber > 0) as has_fiber,
                COUNT(*) FILTER (WHERE nf.is_fiber_correct = TRUE) as marked_correct
            FROM nutritionfacts nf
        """)
        stats = dict(cur.fetchone())
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Products", stats['total'])
    with col2:
        st.metric("Missing Fiber", stats['missing_fiber'])
    with col3:
        st.metric("Has Fiber", stats['has_fiber'])
    with col4:
        st.metric("Marked Correct", stats['marked_correct'])
    
    with st.expander("📋 Category Fiber Defaults", expanded=False):
        defaults_data = [{"Category": k, "Fiber (g/100g)": v} for k, v in sorted(CATEGORY_FIBER_DEFAULTS.items())]
        st.dataframe(defaults_data, use_container_width=True, height=300)
    
    with st.expander("⚠️ Exception Rules", expanded=False):
        for rule in EXCEPTION_RULES:
            st.markdown(f"**{rule['category_prefix']}**: Keywords `{', '.join(rule['keywords'])}` → {rule['fiber']}g")
            st.caption(f"_{rule['reason']}_")
    
    st.divider()
    
    # Initialize session state for fiber estimation
    if 'fiber_updates_ready' not in st.session_state:
        st.session_state.fiber_updates_ready = []
    
    limit_preview = st.number_input("Preview limit (products to show)", min_value=10, max_value=500, value=50)
    
    col1, col2 = st.columns(2)
    run_preview = col1.button("🔍 Preview Fiber Estimates", type="primary")
    apply_now = col2.button("✅ Apply All Estimates", type="secondary")
    
    if run_preview:
        with st.spinner("Fetching products with missing fiber..."):
            with db.connection.cursor() as cur:
                cur.execute("""
                    SELECT 
                        p.product_id,
                        p.sku,
                        p.name,
                        nc.rimi_category_code as category_code,
                        nf.fiber,
                        nf.energy_kj,
                        nf.carbs_sugars,
                        nf.fat_saturated,
                        nf.salt,
                        nf.protein,
                        nf.nutri_score_grade as current_grade,
                        nf.nutri_score_points as current_score
                    FROM products p
                    JOIN nutritionfacts nf ON p.product_id = nf.product_id
                    LEFT JOIN normalized_categories nc ON p.category_id = nc.category_id
                    WHERE (nf.fiber IS NULL OR nf.fiber = 0)
                      AND nf.energy_kj IS NOT NULL
                    ORDER BY p.name
                """)
                products = [dict(row) for row in cur.fetchall()]
        
        if not products:
            st.success("All products with nutrition data already have fiber values!")
            return
        
        st.write(f"Found **{len(products)}** products with missing fiber")
        
        calculator = NutriscoreCalculator()
        results = []
        for product in products:
            new_fiber, source, should_update, match_type = estimate_fiber(
                product.get('name', ''),
                product.get('category_code', ''),
                product.get('fiber')
            )
            
            # Skip products with 0 fiber estimate (category default is 0)
            if new_fiber == 0:
                continue
            
            new_grade = None
            if new_fiber > 0 and all([
                product.get('energy_kj'), 
                product.get('carbs_sugars') is not None,
                product.get('fat_saturated') is not None, 
                product.get('salt') is not None,
                product.get('protein') is not None
            ]):
                try:
                    calc_result = calculator.calculate_single_product(
                        energy_kj=float(product['energy_kj']),
                        sugars=float(product['carbs_sugars']),
                        saturated_fat=float(product['fat_saturated']),
                        salt=float(product['salt']),
                        protein=float(product['protein']),
                        fiber=new_fiber,
                        category_code=product.get('category_code'),
                        product_name=product.get('name'),
                        ingredients_text=product.get('ingredients_text')
                    )
                    if calc_result.get('success'):
                        new_grade = calc_result['grade']
                except Exception:
                    pass
            
            results.append({
                'product_id': product['product_id'],
                'sku': product['sku'],
                'name': product['name'][:50],
                'category': product.get('category_code', 'N/A'),
                'old_fiber': product.get('fiber') or 0,
                'new_fiber': new_fiber,
                'match_type': match_type,
                'before_grade': product.get('current_grade'),
                'new_grade': new_grade,
                'energy_kj': product.get('energy_kj'),
                'sugars': product.get('carbs_sugars'),
                'saturated_fat': product.get('fat_saturated'),
                'salt': product.get('salt'),
                'protein': product.get('protein'),
            })
        
        updates_needed = [r for r in results if r['new_fiber'] > 0]
        st.session_state.fiber_updates_ready = updates_needed
        st.write(f"**{len(updates_needed)}** products will get fiber estimates")
        
        import pandas as pd
        display_cols = ['sku', 'name', 'category', 'old_fiber', 'new_fiber', 'match_type', 'before_grade', 'new_grade']
        df = pd.DataFrame(results[:limit_preview])[display_cols]
        st.dataframe(df, use_container_width=True)
        st.info(f"Click 'Apply All Estimates' button above to apply changes to all {len(updates_needed)} products")
    
    # Show stored preview if available (persists across reruns)
    elif st.session_state.fiber_updates_ready:
        updates_needed = st.session_state.fiber_updates_ready
        st.write(f"**{len(updates_needed)}** products ready for fiber estimation")
        import pandas as pd
        display_cols = ['sku', 'name', 'category', 'old_fiber', 'new_fiber', 'match_type', 'before_grade', 'new_grade']
        df = pd.DataFrame(updates_needed[:limit_preview])[display_cols]
        st.dataframe(df, use_container_width=True)
    
    # Handle Apply button
    if apply_now:
        if not st.session_state.fiber_updates_ready:
            st.warning("Please run Preview first to prepare the list of products to update")
            return
        
        updates_needed = st.session_state.fiber_updates_ready
        st.warning(f"Applying fiber estimates to {len(updates_needed)} products...")
        
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        calculator = NutriscoreCalculator()
        updated_count = 0
        grade_changed_count = 0
        
        for i, result in enumerate(updates_needed):
            status_text.text(f"Processing {i+1}/{len(updates_needed)}: {result['name'][:40]}...")
            
            new_fiber = result['new_fiber']
            
            new_grade = None
            new_score = None
            if all([result.get('energy_kj'), result.get('sugars') is not None, 
                    result.get('saturated_fat') is not None, result.get('salt') is not None,
                    result.get('protein') is not None]):
                try:
                    calc_result = calculator.calculate_single_product(
                        energy_kj=float(result['energy_kj']),
                        sugars=float(result['sugars']),
                        saturated_fat=float(result['saturated_fat']),
                        salt=float(result['salt']),
                        protein=float(result['protein']),
                        fiber=new_fiber,
                        category_code=result['category'],
                        product_name=result.get('name'),
                        ingredients_text=result.get('ingredients_text')
                    )
                    if calc_result.get('success'):
                        new_grade = calc_result['grade']
                        new_score = calc_result['score']
                except Exception:
                    pass
            
            try:
                with db.connection.cursor() as cur:
                    if new_grade:
                        cur.execute("""
                            UPDATE nutritionfacts 
                            SET fiber = %s, 
                                is_fiber_correct = FALSE,
                                nutri_score_grade = %s,
                                nutri_score_points = %s
                            WHERE product_id = %s
                        """, (new_fiber, new_grade, new_score, result['product_id']))
                        if result['before_grade'] != new_grade:
                            grade_changed_count += 1
                    else:
                        cur.execute("""
                            UPDATE nutritionfacts 
                            SET fiber = %s, is_fiber_correct = FALSE
                            WHERE product_id = %s
                        """, (new_fiber, result['product_id']))
                    db.connection.commit()
                    updated_count += 1
            except Exception as e:
                st.error(f"Error updating {result['sku']}: {e}")
            
            progress_bar.progress((i + 1) / len(updates_needed))
        
        status_text.text("Complete!")
        st.session_state.fiber_updates_ready = []  # Clear after applying
        st.success(f"""
        **Results:**
        - Updated: {updated_count} products
        - Grade changed: {grade_changed_count} products
        """)


def section_ingredient_import():
    """Section: Combined AI Ingredient Analysis (Categorization + NOVA4 Suspicion)"""
    from combined_ingredient_analyzer import (
        get_analysis_stats, run_test_batch, run_full_analysis, 
        reset_all_analysis, batch_update_ingredients, BATCH_SIZE,
        fix_incomplete_suspicion
    )
    
    st.header("🧪 Combined Ingredient Analysis")
    st.markdown("""
    **Single AI pass** that categorizes ingredients AND identifies NOVA4 suspicion markers.
    - **Category**: Natural 🌿 vs Processed 🏭
    - **Suspicion Level**: Avoid 🔴 / Limit 🟠 / Caution 🟡 / Clean ✅
    """)
    
    stats = get_analysis_stats()
    
    if stats:
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total", stats['total'])
        with col2:
            st.metric("🌿 Natural", stats['natural_count'])
        with col3:
            st.metric("🏭 Processed", stats['processed_count'])
        with col4:
            st.metric("❓ Unanalyzed", stats['unanalyzed'])
        
        col5, col6, col7, col8 = st.columns(4)
        with col5:
            st.metric("🔴 Avoid", stats['avoid_count'])
        with col6:
            st.metric("🟠 Limit", stats['limit_count'])
        with col7:
            st.metric("🟡 Caution", stats['caution_count'])
        with col8:
            st.metric("✅ Clean", stats['clean_count'])
        
        incomplete = stats.get('incomplete_suspicion', 0)
        if incomplete > 0:
            st.warning(f"⚠️ {incomplete} processed ingredients need suspicion analysis fix")
            if st.button("🔧 Fix Incomplete Suspicion Analysis", type="primary"):
                with st.spinner(f"Fixing {incomplete} ingredients..."):
                    try:
                        result = fix_incomplete_suspicion()
                        st.success(f"Fixed {result.get('processed', 0)} ingredients!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Fix failed: {str(e)}")
        
        analyzed = stats['total'] - stats['unanalyzed']
        if stats['total'] > 0:
            coverage = analyzed / stats['total']
            st.progress(coverage, f"Coverage: {analyzed}/{stats['total']} ({round(coverage * 100, 1)}%)")
    else:
        st.error("Could not load statistics")
        return
    
    st.divider()
    
    if 'combined_running' not in st.session_state:
        st.session_state.combined_running = False
    if 'test_results' not in st.session_state:
        st.session_state.test_results = None
    if 'combined_results' not in st.session_state:
        st.session_state.combined_results = None
    
    st.subheader("🧪 Test Before Full Run")
    st.markdown(f"Run 1-2 test batches ({BATCH_SIZE} ingredients each) to verify AI accuracy before processing all.")
    
    col_test1, col_test2 = st.columns(2)
    
    with col_test1:
        test_batches = st.selectbox("Test batches", [1, 2], index=0)
    
    with col_test2:
        if st.button("🧪 Run Test Batch", type="secondary", disabled=st.session_state.combined_running):
            with st.spinner(f"Testing {test_batches} batch(es)..."):
                try:
                    test_results = run_test_batch(batch_count=test_batches)
                    st.session_state.test_results = test_results
                except Exception as e:
                    st.error(f"Test failed: {str(e)}")
    
    if st.session_state.test_results:
        results = st.session_state.test_results
        st.success(f"Test complete! {len(results)} ingredients analyzed (not saved)")
        
        natural_cnt = sum(1 for r in results if r['category'] == 'natural')
        processed_cnt = sum(1 for r in results if r['category'] == 'processed')
        avoid_cnt = sum(1 for r in results if r['suspicion_level'] == 'avoid')
        limit_cnt = sum(1 for r in results if r['suspicion_level'] == 'limit')
        caution_cnt = sum(1 for r in results if r['suspicion_level'] == 'caution')
        
        st.caption(f"Category: {natural_cnt} natural, {processed_cnt} processed | Suspicion: {avoid_cnt} avoid, {limit_cnt} limit, {caution_cnt} caution")
        
        with st.expander("📋 View Test Results", expanded=True):
            for r in results[:20]:
                cat_emoji = "🌿" if r['category'] == 'natural' else "🏭"
                susp = r['suspicion_level']
                susp_emoji = "🔴" if susp == 'avoid' else "🟠" if susp == 'limit' else "🟡" if susp == 'caution' else "✅"
                note = f" - {r['health_note']}" if r.get('health_note') else ""
                st.markdown(f"{cat_emoji}{susp_emoji} **{r['clean_name']}** ({r.get('suspicion_category', '-')}){note}")
            
            if len(results) > 20:
                st.caption(f"...and {len(results) - 20} more")
        
        col_save, col_clear = st.columns(2)
        with col_save:
            if st.button("💾 Save Test Results to DB", type="primary"):
                db = ProductViewDatabase()
                db._ensure_connection()
                try:
                    batch_update_ingredients(db.connection, results)
                    st.success(f"Saved {len(results)} ingredients to database!")
                    st.session_state.test_results = None
                    st.rerun()
                except Exception as e:
                    st.error(f"Save failed: {str(e)}")
        
        with col_clear:
            if st.button("🗑️ Clear Test Results"):
                st.session_state.test_results = None
                st.rerun()
    
    st.divider()
    
    st.subheader("🚀 Full Analysis")
    
    unanalyzed = stats['unanalyzed'] if stats else 0
    estimated_calls = (unanalyzed // BATCH_SIZE) + 1 if unanalyzed > 0 else 0
    st.caption(f"Unanalyzed: {unanalyzed} | Batch size: {BATCH_SIZE} | Estimated API calls: ~{estimated_calls}")
    
    col_run, col_reset = st.columns(2)
    
    with col_run:
        if unanalyzed == 0:
            st.success("All ingredients analyzed!")
        elif st.button("🚀 Start Full Analysis", type="primary", disabled=st.session_state.combined_running):
            st.session_state.combined_running = True
            
            progress_bar = st.progress(0, "Starting...")
            status_text = st.empty()
            
            def progress_callback(processed, total):
                pct = processed / total if total > 0 else 0
                progress_bar.progress(pct, f"Analyzing: {processed}/{total}")
                status_text.caption(f"Batch complete - {processed} of {total}")
            
            try:
                results = run_full_analysis(progress_callback=progress_callback)
                st.session_state.combined_results = results
                st.session_state.combined_running = False
                st.success(f"Analysis complete! Processed {results.get('processed', 0)} ingredients in {results.get('batches', 0)} batches")
                st.rerun()
            except Exception as e:
                st.session_state.combined_running = False
                st.error(f"Error: {str(e)}")
    
    with col_reset:
        if st.button("🔄 Reset All Analysis", type="secondary"):
            count = reset_all_analysis()
            st.success(f"Reset {count} ingredients for re-analysis")
            st.rerun()
    
    st.divider()
    
    st.subheader("⚠️ Suspicious Ingredients Found")
    
    db = ProductViewDatabase()
    db._ensure_connection()
    
    with db.connection.cursor() as cur:
        cur.execute("""
            SELECT id, ingredient, clean_name, category, suspicion_level, suspicion_category, health_note, frequency
            FROM ingredient_analysis
            WHERE suspicion_level IN ('avoid', 'limit', 'caution')
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
            cat = ing['suspicion_category'] or "-"
            note = ing['health_note'] or ""
            
            level_upper = level.upper() if level else "?"
            st.markdown(f"{emoji} **{level_upper}** | **{clean}** ({cat}) - {note} _(freq: {ing['frequency']})_")
    else:
        st.info("No suspicious ingredients found yet. Run the analysis above.")




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
