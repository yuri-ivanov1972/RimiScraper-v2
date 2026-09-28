"""One-off, photo-only repair for development products without productphotos rows.

Run: python restore_missing_photos.py --execute
Without --execute, the command reports the affected products without fetching or saving.
"""

import argparse
import os
from urllib.parse import urlparse

import psycopg2
from bs4 import BeautifulSoup

from robust_web_client import RobustWebClient


MISSING_PRODUCTS_SQL = """
    SELECT p.product_id, p.sku, p.rimi_url
    FROM products p
    WHERE NOT EXISTS (
        SELECT 1 FROM productphotos pp WHERE pp.product_id = p.product_id
    )
    ORDER BY p.product_id
"""


def missing_products(conn):
    with conn.cursor() as cur:
        cur.execute(MISSING_PRODUCTS_SQL)
        return cur.fetchall()


def photo_from_page(client, sku, page_url):
    """Fetch one product and return (verified photo URL, failure reason)."""
    expected_url = f"https://www.rimi.lv/e-veikals/lv/produkti/p/{sku}"
    if page_url != expected_url or not sku.isdigit():
        return None, "invalid product URL or SKU"

    response = client.fetch_with_retry(page_url, max_attempts=2, base_delay=1)
    if response is None:
        return None, f"page unavailable (HTTP {client.last_fetch_status_code or 'network error'})"
    soup = BeautifulSoup(response.text, "html.parser")
    title = soup.find("h1", class_="name") or soup.find("h1")
    if not title or not title.get_text(strip=True):
        return None, "product page has no title"

    candidates = client._extract_photos(soup)
    # Rimi now exposes some images only in social metadata, not in <img> tags.
    og_image = soup.select_one('meta[property="og:image"]')
    if og_image:
        candidates.append(og_image.get("content"))

    for candidate in filter(None, candidates):
        parsed = urlparse(candidate)
        if parsed.scheme != "https" or parsed.hostname != "rimibaltic-res.cloudinary.com":
            continue
        # Remove Cloudinary's fallback transformation. A missing image then
        # returns 404 instead of displaying a generic replacement photo.
        url = candidate.replace("/d_ecommerce:backend-fallback.png/", "/")
        if f"/MAT_{sku}_" not in url:
            continue
        try:
            with client.session.get(url, timeout=20, stream=True) as image:
                if image.status_code == 200 and image.headers.get(
                    "Content-Type", ""
                ).lower().startswith("image/"):
                    return url, None
        except Exception:
            continue
    return None, "no verified product image on page"


def save_if_missing(conn, product_id, sku, photo_url):
    """Add a photo only while the original product is still photo-less."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM products WHERE product_id = %s AND sku = %s FOR UPDATE",
                (product_id, sku),
            )
            if cur.fetchone() is None:
                conn.rollback()
                return False, "product no longer exists"
            cur.execute(
                """
                INSERT INTO productphotos (product_id, photo_url, is_primary)
                SELECT %s, %s, TRUE
                WHERE NOT EXISTS (
                    SELECT 1 FROM productphotos WHERE product_id = %s
                )
                RETURNING photo_id
                """,
                (product_id, photo_url, product_id),
            )
            inserted = cur.fetchone() is not None
        conn.commit()
        return (True, None) if inserted else (False, "photo already exists")
    except Exception as exc:
        conn.rollback()
        return False, f"save error: {exc}"


def repair(conn, client):
    products = missing_products(conn)
    print(f"Before retry: {len(products)} products without photos")
    recovered = 0
    unresolved = []
    for product_id, sku, page_url in products:
        try:
            photo, reason = photo_from_page(client, sku, page_url)
            if photo:
                saved, reason = save_if_missing(conn, product_id, sku, photo)
                if saved:
                    recovered += 1
                    print(f"Recovered product {product_id} (SKU {sku})")
                    continue
        except Exception as exc:
            reason = f"extraction error: {exc}"
        unresolved.append((product_id, sku, reason))
        print(f"Unresolved product {product_id} (SKU {sku}): {reason}")

    remaining = {row[0] for row in missing_products(conn)}
    print(f"After retry: {len(remaining)} products without photos; {recovered} recovered")
    for product_id, sku, reason in unresolved:
        if product_id in remaining:
            print(f"Still missing: product {product_id}, SKU {sku} — {reason}")
    return recovered, remaining


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Fetch and save missing photos")
    args = parser.parse_args()
    if (
        os.environ.get("DEV_MODE", "").lower() not in ("true", "1", "yes")
        and os.environ.get("ENVIRONMENT", "").lower() not in ("development", "dev")
    ):
        raise RuntimeError("Photo repair requires development mode")
    db_url = os.environ["DATABASE_URL"]
    if os.environ.get("PROD_DATABASE_URL") == db_url:
        raise RuntimeError("Refusing to repair the production database")
    with psycopg2.connect(db_url, connect_timeout=10) as conn:
        if not args.execute:
            rows = missing_products(conn)
            print(f"{len(rows)} products without photos")
            for product_id, sku, url in rows:
                print(f"Product {product_id}, SKU {sku}: {url}")
            return
        client = RobustWebClient(status_callback=lambda _message: None)
        repair(conn, client)


if __name__ == "__main__":
    main()