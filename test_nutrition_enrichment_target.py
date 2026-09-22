"""Tests for targeted product enrichment lookup."""

from nutrition_enrichment_service import NutritionEnrichmentService


def product_row(product_id, sku, name="Test product"):
    return {
        "product_id": product_id,
        "sku": sku,
        "name": name,
        "category_id": 1,
        "category_name": "Test",
        "energy_kcal": None,
        "fat_total": None,
        "fat_saturated": None,
        "carbs_total": None,
        "carbs_sugars": None,
        "protein": None,
        "salt": None,
        "fiber": None,
    }


class FakeCursor:
    def __init__(self, connection):
        self.connection = connection
        self.row = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def execute(self, query, params):
        normalized = " ".join(query.split())
        value = params[0]
        self.connection.queries.append((normalized, params))
        eligible = "p.needs_enrichment = TRUE" in normalized
        by_sku = "WHERE p.sku = %s" in normalized or "WHERE sku = %s" in normalized
        by_id = (
            "WHERE p.product_id = %s" in normalized
            or "WHERE product_id = %s" in normalized
        )
        candidates = self.connection.rows
        if by_sku:
            candidates = [row for row in candidates if row["sku"] == value]
        elif by_id:
            candidates = [
                row for row in candidates if row["product_id"] == value
            ]
        if eligible:
            candidates = [
                row for row in candidates
                if row["needs_enrichment"] and not row["enrichment_reviewed"]
            ]
        self.row = candidates[0] if candidates else None

    def fetchone(self):
        return self.row


class FakeConnection:
    def __init__(self, rows):
        self.rows = rows
        self.queries = []
        self.closed = False

    def cursor(self, cursor_factory=None):
        return FakeCursor(self)

    def close(self):
        self.closed = True


def service_with_rows(rows):
    connection = FakeConnection(rows)
    service = object.__new__(NutritionEnrichmentService)
    service.status_callback = lambda _message: None
    service._get_connection = lambda: connection
    return service, connection


def eligible(row):
    return {
        **row,
        "needs_enrichment": True,
        "enrichment_reviewed": False,
    }


def test_exact_sku_has_priority_over_same_numeric_product_id():
    service, connection = service_with_rows([
        eligible(product_row(123, "OTHER", "ID match")),
        eligible(product_row(999, "123", "SKU match")),
    ])

    product = service.get_product_for_enrichment("123")

    assert product.product_id == 999
    assert len(connection.queries) == 1
    assert connection.closed


def test_numeric_identifier_falls_back_to_product_id():
    service, _connection = service_with_rows([
        eligible(product_row(123, "SKU-123", "ID match")),
    ])

    product = service.get_product_for_enrichment("123")

    assert product.product_id == 123


def test_ineligible_product_gets_clear_message():
    row = {
        **product_row(5, "SKU-5"),
        "needs_enrichment": False,
        "enrichment_reviewed": True,
    }
    service, _connection = service_with_rows([row])

    try:
        service.get_product_for_enrichment("SKU-5")
    except ValueError as exc:
        assert "does not need enrichment" in str(exc)
    else:
        raise AssertionError("Expected an ineligible-product error")


def test_unknown_identifier_gets_not_found_message():
    service, _connection = service_with_rows([])

    try:
        service.get_product_for_enrichment("UNKNOWN")
    except LookupError as exc:
        assert "No product found" in str(exc)
    else:
        raise AssertionError("Expected a not-found error")


def test_empty_identifier_is_rejected_without_database_work():
    service, connection = service_with_rows([])

    try:
        service.get_product_for_enrichment(" ")
    except ValueError as exc:
        assert "Enter a product ID or SKU" in str(exc)
    else:
        raise AssertionError("Expected an empty-input error")

    assert connection.queries == []