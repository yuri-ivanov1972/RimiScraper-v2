"""Tests for category-filtered nutrition enrichment batches."""

from streamlit.testing.v1 import AppTest

import nutrition_enrichment_service
from nutrition_enrichment_service import (
    EnrichmentBatch,
    NutritionEnrichmentService,
    ProductForEnrichment,
)


def nutrition_enrichment_test_app():
    from main import section_nutrition_enrichment

    section_nutrition_enrichment()


class RecordingCursor:
    def __init__(self, rows):
        self.rows = rows
        self.query = ""
        self.params = ()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def execute(self, query, params=()):
        self.query = " ".join(query.split())
        self.params = params

    def fetchall(self):
        return list(self.rows)


class RecordingConnection:
    def __init__(self, rows):
        self.cursor_instance = RecordingCursor(rows)
        self.closed = False

    def cursor(self, cursor_factory=None):
        return self.cursor_instance

    def close(self):
        self.closed = True


def service_with_rows(rows):
    connection = RecordingConnection(rows)
    service = object.__new__(NutritionEnrichmentService)
    service.status_callback = lambda _message: None
    service._get_connection = lambda: connection
    return service, connection


def product_row():
    return {
        "product_id": 7,
        "sku": "SKU-7",
        "name": "Test",
        "category_id": 12,
        "category_name": "Child",
        "energy_kcal": None,
        "fat_total": None,
        "fat_saturated": None,
        "carbs_total": None,
        "carbs_sugars": None,
        "protein": None,
        "salt": None,
        "fiber": None,
        "enrichment_skipped": False,
    }


class RecordingEnrichmentService:
    batch_requests = []
    target_requests = []

    def __init__(self, status_callback=None):
        self.status_callback = status_callback

    def get_enrichment_stats(self):
        return {
            "needs_enrichment": 2,
            "reviewed": 0,
            "from_usda": 0,
            "from_rimi": 0,
            "skipped": 0,
        }

    def get_enrichment_categories(self):
        return [
            {
                "category_id": 3,
                "category_path": "Food › Dairy",
                "product_count": 1,
            },
            {
                "category_id": 8,
                "category_path": "Food › Bakery",
                "product_count": 1,
            },
        ]

    def get_products_needing_enrichment(self, limit, category_id=None):
        self.batch_requests.append({
            "limit": limit,
            "category_id": category_id,
        })
        return [
            ProductForEnrichment(
                product_id=7,
                sku="SKU-7",
                name="Batch product",
            )
        ]

    def get_product_for_enrichment(self, identifier):
        self.target_requests.append(identifier)
        return ProductForEnrichment(
            product_id=9,
            sku=str(identifier),
            name="Target product",
        )

    def process_batch(self, products):
        return EnrichmentBatch()


def test_submitted_category_stays_fixed_across_reruns_and_targeted_lookup(
    monkeypatch,
):
    RecordingEnrichmentService.batch_requests = []
    RecordingEnrichmentService.target_requests = []
    monkeypatch.setattr(
        nutrition_enrichment_service,
        "NutritionEnrichmentService",
        RecordingEnrichmentService,
    )

    app = AppTest.from_function(nutrition_enrichment_test_app)
    app.run()

    app.selectbox(key="enrichment_category_id").select(3)
    next(button for button in app.button if button.label == "🔄 Load Batch").click().run()

    assert RecordingEnrichmentService.batch_requests == [{
        "limit": 20,
        "category_id": 3,
    }]
    assert app.session_state.enrichment_batch_category_id == 3
    assert app.session_state.enrichment_batch_scope == "Food › Dairy (1 products)"

    app.selectbox(key="enrichment_category_id").select(8).run()

    assert RecordingEnrichmentService.batch_requests == [{
        "limit": 20,
        "category_id": 3,
    }]
    assert any(
        "Batch · Food › Dairy (1 products)" in message.value
        for message in app.info
    )

    app.text_input(key="enrichment_target_identifier").set_value("SKU-9")
    next(
        button
        for button in app.button
        if button.label == "🔍 Find and process"
    ).click().run()

    assert RecordingEnrichmentService.target_requests == ["SKU-9"]
    assert RecordingEnrichmentService.batch_requests == [{
        "limit": 20,
        "category_id": 3,
    }]


def test_all_categories_preserves_unfiltered_batch_query_and_limit():
    service, connection = service_with_rows([product_row()])

    products = service.get_products_needing_enrichment(
        limit=20,
        offset=5,
    )

    assert len(products) == 1
    assert "selected_categories" not in connection.cursor_instance.query
    assert connection.cursor_instance.params == (20, 5)


def test_selected_category_uses_recursive_descendant_scope():
    service, connection = service_with_rows([product_row()])

    service.get_products_needing_enrichment(
        limit=10,
        category_id=3,
    )

    query = connection.cursor_instance.query
    assert "WITH RECURSIVE selected_categories" in query
    assert "child.parent_category_id = parent.category_id" in query
    assert "p.category_id IN" in query
    assert connection.cursor_instance.params == (3, 10, 0)


def test_category_options_include_hierarchy_and_eligible_counts():
    rows = [{
        "category_id": 3,
        "category_path": "Food › Dairy",
        "product_count": 14,
    }]
    service, connection = service_with_rows(rows)

    categories = service.get_enrichment_categories()

    assert categories == rows
    query = connection.cursor_instance.query
    assert "WITH RECURSIVE category_paths" in query
    assert "descendants" in query
    assert "products.needs_enrichment = TRUE" in query
    assert "COALESCE(products.enrichment_reviewed, FALSE) = FALSE" in query
    assert connection.closed