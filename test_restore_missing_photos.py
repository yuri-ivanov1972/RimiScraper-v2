"""Checks for the photo-only repair path."""

from argparse import Namespace

import pytest

from restore_missing_photos import choose_database, main, photo_from_page, save_if_missing


class Response:
    def __init__(self, text="", status=200, content_type="image/webp"):
        self.text = text
        self.status_code = status
        self.headers = {"Content-Type": content_type}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class Session:
    def __init__(self, status=200):
        self.status = status
        self.requested = None

    def get(self, url, **kwargs):
        self.requested = url
        return Response(status=self.status)


class Client:
    last_fetch_status_code = 200

    def __init__(self, image_status=200):
        self.session = Session(image_status)

    def fetch_with_retry(self, _url, **_kwargs):
        return Response(
            '<h1 class="name">Product</h1>'
            '<meta property="og:image" content="'
            'https://rimibaltic-res.cloudinary.com/image/upload/'
            'b_white/d_ecommerce:backend-fallback.png/MAT_123_PCE_LV">'
        )

    def _extract_photos(self, _soup):
        return []


def test_metadata_image_is_verified_without_placeholder_fallback():
    client = Client()
    photo, reason = photo_from_page(
        client, "123", "https://www.rimi.lv/e-veikals/lv/produkti/p/123"
    )
    assert reason is None
    assert photo == client.session.requested
    assert "/d_ecommerce:backend-fallback.png/" not in photo


def test_missing_cloudinary_image_is_not_saved_as_placeholder():
    client = Client(image_status=404)
    photo, reason = photo_from_page(
        client, "123", "https://www.rimi.lv/e-veikals/lv/produkti/p/123"
    )
    assert photo is None
    assert reason == "no verified product image on page"


def test_product_url_must_match_sku():
    client = Client()
    photo, reason = photo_from_page(
        client, "123", "https://www.rimi.lv/e-veikals/lv/produkti/p/456"
    )
    assert photo is None
    assert reason == "invalid product URL or SKU"
    assert client.session.requested is None


class Cursor:
    def __init__(self, rows):
        self.rows = iter(rows)
        self.queries = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, query, params):
        self.queries.append((" ".join(query.split()), params))

    def fetchone(self):
        return next(self.rows)


class Connection:
    def __init__(self, rows):
        self.cursor_instance = Cursor(rows)
        self.committed = False
        self.rolled_back = False

    def cursor(self):
        return self.cursor_instance

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


def test_save_only_inserts_if_photo_is_still_missing():
    conn = Connection([(1,), (7,)])
    saved, reason = save_if_missing(conn, 12, "123", "https://example.com/photo")
    assert saved and reason is None and conn.committed
    assert len(conn.cursor_instance.queries) == 2
    assert "FOR UPDATE" in conn.cursor_instance.queries[0][0]
    assert "NOT EXISTS" in conn.cursor_instance.queries[1][0]
    assert "DELETE" not in conn.cursor_instance.queries[1][0]


def test_existing_photo_is_not_replaced():
    conn = Connection([(1,), None])
    saved, reason = save_if_missing(conn, 12, "123", "https://example.com/photo")
    assert not saved and reason == "photo already exists"
    assert conn.committed


def options(production=False, execute=False, confirm_production=False):
    return Namespace(
        production=production,
        execute=execute,
        confirm_production=confirm_production,
    )


def test_production_check_uses_separate_production_connection():
    env = {"DATABASE_URL": "development", "PROD_DATABASE_URL": "production"}
    assert choose_database(options(production=True), env) == "production"
    assert choose_database(options(), {**env, "DEV_MODE": "true"}) == "development"


def test_production_write_requires_separate_confirmation():
    env = {"DATABASE_URL": "development", "PROD_DATABASE_URL": "production"}
    with pytest.raises(ValueError, match="--confirm-production"):
        choose_database(options(production=True, execute=True), env)
    assert choose_database(
        options(production=True, execute=True, confirm_production=True), env
    ) == "production"
    with pytest.raises(ValueError, match="requires --production and --execute"):
        choose_database(options(production=True, confirm_production=True), env)


def test_production_and_development_targets_must_be_distinct():
    env = {"DATABASE_URL": "same", "PROD_DATABASE_URL": "same", "DEV_MODE": "true"}
    with pytest.raises(ValueError, match="distinct"):
        choose_database(options(production=True), env)
    with pytest.raises(ValueError, match="Refusing"):
        choose_database(options(), env)


def test_default_development_requires_development_mode():
    with pytest.raises(ValueError, match="development mode"):
        choose_database(
            options(),
            {"DATABASE_URL": "development", "PROD_DATABASE_URL": "production"},
        )


def test_production_check_is_read_only(monkeypatch, capsys):
    class ReadOnlyCursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, query):
            assert "SELECT p.product_id" in query
            assert "INSERT" not in query

        def fetchall(self):
            return [(42, "123", "https://www.rimi.lv/e-veikals/lv/produkti/p/123")]

    class ReadOnlyConnection:
        def __init__(self):
            self.readonly = False
            self.closed = False

        def set_session(self, readonly):
            self.readonly = readonly

        def cursor(self):
            assert self.readonly
            return ReadOnlyCursor()

        def close(self):
            self.closed = True

    connection = ReadOnlyConnection()
    monkeypatch.setenv("DATABASE_URL", "development")
    monkeypatch.setenv("PROD_DATABASE_URL", "production")
    monkeypatch.setattr(
        "restore_missing_photos.psycopg2.connect",
        lambda url, **_kwargs: connection if url == "production" else None,
    )
    monkeypatch.setattr("sys.argv", ["restore_missing_photos.py", "--production"])
    main()

    assert connection.readonly and connection.closed
    assert "PRODUCTION read-only check: 1 products" in capsys.readouterr().out