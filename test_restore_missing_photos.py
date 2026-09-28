"""Checks for the photo-only repair path."""

from restore_missing_photos import photo_from_page, save_if_missing


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