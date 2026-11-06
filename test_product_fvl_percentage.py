"""Product percentage tests; database tests use connection-local temporary tables."""

import os
from types import SimpleNamespace

import psycopg2
from psycopg2.extras import RealDictCursor
import pytest

from nutrition_editing import save_nutrition_edit
from nutriscore_calculator import NutriscoreCalculator, validate_fvl_percentage


VALUES = dict(
    energy_kj=1000, energy_kcal=240, fat_total=20, fat_saturated=2,
    carbs_total=15, carbs_sugars=5, fiber=3, protein=12, salt=0.4,
)


@pytest.fixture
def connection():
    url = os.getenv("DATABASE_URL")
    if not url or url == os.getenv("PROD_DATABASE_URL"):
        pytest.skip("Requires a distinct development database")
    conn = psycopg2.connect(url, cursor_factory=RealDictCursor)
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TEMP TABLE normalized_categories (
                category_id integer PRIMARY KEY, nutriscore_category_type text
            );
            CREATE TEMP TABLE products (
                product_id integer PRIMARY KEY, sku text, name text, category_id integer,
                nutrition_source text, needs_enrichment boolean, enrichment_reviewed boolean,
                updated_at timestamptz
            );
            CREATE TEMP TABLE nutritionfacts (
                product_id integer PRIMARY KEY, ingredients_text text,
                energy_kj integer, energy_kcal integer, fat_total numeric,
                fat_saturated numeric, carbs_total numeric, carbs_sugars numeric,
                fiber numeric, protein numeric, salt numeric,
                fruit_veg_legume_percent numeric(5,2)
                    CHECK (fruit_veg_legume_percent BETWEEN 0 AND 100),
                nutri_score_grade char(1), nutri_score_points integer,
                nutrition_manual_edit boolean, is_fiber_correct boolean,
                usda_fdc_id integer, data_source_date timestamptz
            );
            INSERT INTO normalized_categories VALUES (1, 'full_fvn');
            INSERT INTO products (product_id, sku, name, category_id) VALUES (1, 'TEST', 'Test product', 1);
        """)
    conn.commit()
    try:
        yield conn
    finally:
        conn.close()


def stored(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM nutritionfacts WHERE product_id = 1")
        return cur.fetchone()


def calculate(conn, **kwargs):
    return NutriscoreCalculator(conn).calculate_single_product(
        energy_kj=1000, sugars=5, saturated_fat=2, salt=0.4, protein=12,
        fiber=3, total_fat=20, category_id=1, **kwargs,
    )


@pytest.mark.parametrize("value", [-1, 101, float("nan"), float("inf"), "invalid"])
def test_invalid_percentages_are_rejected(value):
    with pytest.raises(ValueError):
        validate_fvl_percentage(value)


def test_first_save_decimal_reopen_zero_and_clear(connection):
    save_nutrition_edit(connection, 1, VALUES, 83.25, False)
    assert float(stored(connection)["fruit_veg_legume_percent"]) == 83.25
    assert calculate(connection, product_id=1)["classification"]["fruits_veg_nuts_percent"] == 83.25

    zero = save_nutrition_edit(connection, 1, VALUES, 0, False)
    assert float(stored(connection)["fruit_veg_legume_percent"]) == 0
    assert calculate(connection, product_id=1)["classification"]["fruits_veg_nuts_percent"] == 0

    cleared = save_nutrition_edit(connection, 1, VALUES, None, False)
    assert stored(connection)["fruit_veg_legume_percent"] is None
    assert cleared["classification"]["fruits_veg_nuts_percent"] == 100
    assert zero["score"] != cleared["score"]
    assert calculate(connection, product_id=1)["classification"]["fruit_veg_legume_source"] == "category"


def test_failed_score_and_invalid_value_do_not_partially_save(connection):
    save_nutrition_edit(connection, 1, VALUES, 42, False)
    with pytest.raises(ValueError):
        save_nutrition_edit(connection, 1, VALUES, 101, False)
    assert float(stored(connection)["fruit_veg_legume_percent"]) == 42
    with connection.cursor() as cur:
        cur.execute("UPDATE products SET category_id = 999 WHERE product_id = 1")
    connection.commit()
    with pytest.raises(ValueError, match="No normalized category"):
        save_nutrition_edit(connection, 1, VALUES, 90, False)
    assert float(stored(connection)["fruit_veg_legume_percent"]) == 42


def execute_query(conn):
    def execute(query, params=None, fetch=False):
        with conn.cursor() as cur:
            cur.execute(query, params)
            return cur.fetchall() if fetch else None
    return execute


def test_scrapers_and_enrichment_preserve_override_and_score(connection):
    from database_updater import DatabaseUpdater
    from enhanced_database_updater import EnhancedDatabaseUpdater
    from nutrition_enrichment_service import NutritionEnrichmentService

    expected = save_nutrition_edit(connection, 1, VALUES, 0, False)
    basic = object.__new__(DatabaseUpdater)
    basic.conn = connection
    basic.status_callback = lambda _: None
    basic._execute_query = execute_query(connection)
    assert basic.add_nutrition_data(1, VALUES)
    assert float(stored(connection)["fruit_veg_legume_percent"]) == 0
    assert stored(connection)["nutri_score_points"] == expected["score"]

    enhanced = object.__new__(EnhancedDatabaseUpdater)
    enhanced.conn = connection
    enhanced.status_callback = lambda _: None
    enhanced._execute_query = execute_query(connection)
    assert enhanced.force_update_nutrition_data(1, VALUES)
    assert float(stored(connection)["fruit_veg_legume_percent"]) == 0
    assert stored(connection)["nutri_score_points"] == expected["score"]

    # A non-closing proxy lets us inspect this temporary test database after
    # the enrichment service closes its normal per-request connection.
    class Proxy:
        def __getattr__(self, name):
            return getattr(connection, name)

        def close(self):
            pass

    service = object.__new__(NutritionEnrichmentService)
    service.status_callback = lambda _: None
    service._get_connection = lambda: Proxy()
    match = SimpleNamespace(
        product=SimpleNamespace(product_id=1, sku="TEST", name="Test product", category_id=1),
        usda_match=SimpleNamespace(fdc_id=1, nutrition=SimpleNamespace(**VALUES)),
        status="pending",
    )
    assert service.save_enrichment(match)
    assert float(stored(connection)["fruit_veg_legume_percent"]) == 0
    assert stored(connection)["nutri_score_points"] == expected["score"]


def test_product_recalculation_and_batch_use_current_override(connection):
    from main import recalculate_nutriscore_for_product_data

    expected = save_nutrition_edit(connection, 1, VALUES, 0, False)
    db = SimpleNamespace(connection=connection, _ensure_connection=lambda: None)
    product = dict(
        product_id=1, sku="TEST", name="Test product", category_id=1, energy_kj=1000, sugars=5, saturated_fat=2,
        salt=0.4, protein=12, fiber=3, fat_total=20,
    )
    result = recalculate_nutriscore_for_product_data(db, product)
    assert result["success"], result
    assert stored(connection)["nutri_score_points"] == expected["score"]
    result = NutriscoreCalculator(connection).batch_calculate([product])[0]
    assert result["classification"]["fruits_veg_nuts_percent"] == 0


@pytest.mark.parametrize("percentage", [83.25, 0.0, 100.0])
def test_products_editor_save_clear_and_reopen(connection, monkeypatch, percentage):
    from streamlit.testing.v1 import AppTest
    import main

    save_nutrition_edit(connection, 1, VALUES, None, False)
    def get_product_details(_):
        with connection.cursor() as cur:
            cur.execute(
                "SELECT nf.*, p.name, p.category_id, nc.nutriscore_category_type "
                "FROM nutritionfacts nf JOIN products p USING(product_id) "
                "JOIN normalized_categories nc USING(category_id)"
            )
            return dict(cur.fetchone(), sku="")

    monkeypatch.setattr(main, "ProductViewDatabase", lambda: SimpleNamespace(
        connection=connection, _ensure_connection=lambda: None, close=lambda: None,
        get_product_details=get_product_details,
    ))
    monkeypatch.setattr(main, "render_nova_edit_form", lambda *_: None)
    code = """
import streamlit as st
from main import render_product_detail_view
st.session_state.selected_product_id = 1
render_product_detail_view()
"""
    app = AppTest.from_string(code)
    app.run(timeout=30)
    assert not app.exception
    assert app.metric[-1].value == "100%"
    # Reproduce the reported action: type a number and save, no checkbox step.
    app.number_input(key="fvl_percentage_1").set_value(percentage)
    next(b for b in app.button if "Saglabāt" in b.label).click().run()
    assert not app.exception
    assert not app.error
    assert float(stored(connection)["fruit_veg_legume_percent"]) == percentage
    assert app.metric[-1].value == f"{percentage:g}%"
    assert any(c.value == "Avots: manuāli ievadīts" for c in app.caption)
    expected = calculate(connection, fruits_veg_nuts=percentage)
    assert stored(connection)["nutri_score_points"] == expected["score"]

    reopened = AppTest.from_string(code)
    reopened.run()
    assert not reopened.exception
    assert reopened.number_input(key="fvl_percentage_1").value == percentage
    assert reopened.metric[-1].value == f"{percentage:g}%"
    reopened.number_input(key="fvl_percentage_1").set_value(None)
    next(b for b in reopened.button if "Saglabāt" in b.label).click().run()
    assert not reopened.exception
    assert not reopened.error
    assert stored(connection)["fruit_veg_legume_percent"] is None
    assert reopened.metric[-1].value == "100%"
    assert any(c.value == "Avots: kategorijas noklusējums" for c in reopened.caption)
    assert stored(connection)["nutri_score_points"] == calculate(connection)["score"]
    fresh = AppTest.from_string(code).run()
    assert not fresh.exception
    assert fresh.number_input(key="fvl_percentage_1").value is None
    assert fresh.metric[-1].value == "100%"


def test_development_schema_setup_refuses_production(monkeypatch):
    from scripts.apply_development_schema import apply_development_schema

    def must_not_connect(*args, **kwargs):
        pytest.fail("Unsafe schema setup attempted a database connection")

    monkeypatch.setattr("scripts.apply_development_schema.psycopg2.connect", must_not_connect)
    with pytest.raises(RuntimeError, match="development mode"):
        apply_development_schema({"DATABASE_URL": "prod", "ENVIRONMENT": "production"})
    with pytest.raises(RuntimeError, match="distinct development"):
        apply_development_schema(
            {"DATABASE_URL": "same", "PROD_DATABASE_URL": "same", "DEV_MODE": "true"}
        )
