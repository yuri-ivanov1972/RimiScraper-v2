import json
import unicodedata
import pytest

from bs4 import BeautifulSoup

from brand_producer import (
    canonical_entity_name,
    extract_brand_producer,
    normalize_entity_name,
    upsert_brand_producer,
)


def _product_page(details_html: str) -> BeautifulSoup:
    encoded = json.dumps(details_html, ensure_ascii=True)[1:-1]
    return BeautifulSoup(
        f"""
        <html><script>
        Storefront.product_details_page = {{
          tabs: [{{identifier: "details", html: "{encoded}"}}]
        }};
        </script></html>
        """,
        "html.parser",
    )


def test_normalization_handles_unicode_whitespace_and_case():
    decomposed = unicodedata.normalize("NFD", "Žagariņš")
    assert normalize_entity_name(f"  {decomposed}\n SIA ") == "žagariņš sia"
    assert canonical_entity_name("  Orkla \n Latvija  SIA ") == "Orkla Latvija SIA"
    assert normalize_entity_name(" \t ") is None


def test_extracts_brand_and_producer_from_rimi_details():
    soup = _product_page(
        """
        <div class="product__list-wrapper -basic">
          <li class="item"><span>Zīmols</span>
            <div class="text"><p> Staburadze </p></div>
          </li>
          <li class="item"><span>Ražotājs</span>
            <div class="text"><p>Orkla Latvija SIA</p></div>
          </li>
        </div>
        """
    )
    assert extract_brand_producer(soup) == {
        "brand": "Staburadze",
        "producer": "Orkla Latvija SIA",
    }


def test_missing_or_partial_values_are_nullable():
    soup = _product_page(
        '<li class="item"><span>Zīmols</span><div class="text"><p>Rimi</p></div></li>'
    )
    assert extract_brand_producer(soup) == {"brand": "Rimi", "producer": None}
    assert extract_brand_producer(BeautifulSoup("<html></html>", "html.parser")) == {
        "brand": None,
        "producer": None,
    }


class _FakeCursor:
    def __init__(self):
        self.queries = []
        self._result = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, query, params=None):
        compact = " ".join(query.split())
        self.queries.append((compact, params))
        if "INSERT INTO brands" in compact:
            self._result = {"brand_id": 11}
        elif "INSERT INTO producers" in compact:
            self._result = {"producer_id": 22}

    def fetchone(self):
        return self._result


class _FakeConnection:
    def __init__(self):
        self.cursor_instance = _FakeCursor()

    def cursor(self):
        return self.cursor_instance


def test_upsert_preserves_canonical_fields_and_creates_relationship():
    connection = _FakeConnection()
    result = upsert_brand_producer(
        connection,
        7,
        brand_name="  Staburadze ",
        producer_name="ORKLA Latvija SIA",
    )
    assert result == {"brand_id": 11, "producer_id": 22}
    queries = connection.cursor_instance.queries
    assert queries[0][1] == ("Staburadze", "staburadze")
    assert queries[1][1] == ("ORKLA Latvija SIA", "orkla latvija sia")
    assert "SET updated_at = CURRENT_TIMESTAMP" in queries[0][0]
    assert "name = EXCLUDED.name" not in queries[0][0]
    assert "website_url" not in queries[0][0]
    assert any("UPDATE products SET brand_id = %s, producer_id = %s" in q for q, _ in queries)
    assert any("ON CONFLICT (brand_id, producer_id) DO NOTHING" in q for q, _ in queries)


def test_empty_values_do_not_create_unknowns_or_clear_existing_links():
    connection = _FakeConnection()
    result = upsert_brand_producer(
        connection, 7, brand_name=" ", producer_name=None
    )
    assert result == {"brand_id": None, "producer_id": None}
    assert connection.cursor_instance.queries == []


def test_backfill_argument_validation_and_safe_resume_contract():
    from brand_producer_backfill import backfill_brand_producer

    connection = _FakeConnection()
    with pytest.raises(ValueError):
        backfill_brand_producer(connection, limit=0)


class _BackfillCursor:
    def __init__(self, rows):
        self.rows = rows
        self.selected = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, query, _params=None):
        if "SELECT product_id, sku, rimi_url" in query:
            self.selected = True

    def fetchall(self):
        if self.selected:
            self.selected = False
            rows, self.rows = self.rows, []
            return rows
        return []


class _BackfillConnection:
    def __init__(self, rows):
        self.cursor_instance = _BackfillCursor(rows)
        self.commits = 0
        self.rollbacks = 0

    def cursor(self, **_kwargs):
        return self.cursor_instance

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class _Response:
    text = "<html></html>"


class _BackfillWebClient:
    last_fetch_status_code = None

    def fetch_with_retry(self, url):
        return None if url.endswith("/failed") else _Response()


class _NotFoundWebClient:
    last_fetch_status_code = 404

    def fetch_with_retry(self, _url):
        return None


def test_backfill_failure_freezes_safe_resume_before_failed_row():
    from brand_producer_backfill import backfill_brand_producer

    connection = _BackfillConnection(
        [
            {"product_id": 10, "sku": "A", "rimi_url": "https://rimi/failed"},
            {"product_id": 11, "sku": "B", "rimi_url": "https://rimi/ok"},
        ]
    )
    result = backfill_brand_producer(
        connection,
        batch_size=2,
        start_id=7,
        delay_seconds=0,
        web_client=_BackfillWebClient(),
    )
    assert result["attempted"] == 2
    assert result["failure_count"] == 1
    assert result["last_product_id"] == 11
    assert result["resume_after_product_id"] == 7
    assert connection.commits == 1


def test_backfill_reports_404_as_unavailable_without_freezing_resume():
    from brand_producer_backfill import backfill_brand_producer

    connection = _BackfillConnection(
        [{"product_id": 10, "sku": "A", "rimi_url": "https://rimi/missing"}]
    )
    result = backfill_brand_producer(
        connection,
        batch_size=1,
        start_id=7,
        delay_seconds=0,
        web_client=_NotFoundWebClient(),
    )
    assert result["failure_count"] == 0
    assert result["unavailable_pages"] == 1
    assert result["resume_after_product_id"] == 10