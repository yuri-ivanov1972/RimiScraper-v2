"""Tests for category-filtered nutrition enrichment batches."""

from nutrition_enrichment_service import NutritionEnrichmentService


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