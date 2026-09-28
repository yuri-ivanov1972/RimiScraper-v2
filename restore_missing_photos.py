"""One-off, photo-only repair for products without productphotos rows.

Check production (read-only): python restore_missing_photos.py --production
Repair production: python restore_missing_photos.py --production --execute --confirm-production
Development is the default; without --execute, no pages are fetched or saved.
"""

import argparse
import os
from contextlib import closing
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


def choose_database(args, environ):
    """Require an independently configured production URL and explicit write consent."""
    if args.confirm_production and not (args.production and args.execute):
        raise ValueError("--confirm-production requires --production and --execute")
    if args.production:
        prod_url = environ.get("PROD_DATABASE_URL")
        dev_url = environ.get("DATABASE_URL")
        if not prod_url or not dev_url or prod_url == dev_url:
            raise ValueError("Production requires distinct PROD_DATABASE_URL and DATABASE_URL")
        if args.execute and not args.confirm_production:
            raise ValueError(
                "Production repair requires --production --execute --confirm-production"
            )
        return prod_url

    if (
        environ.get("DEV_MODE", "").lower() not in ("true", "1", "yes")
        and environ.get("ENVIRONMENT", "").lower() not in ("development", "dev")
    ):
        raise ValueError("Development photo repair requires development mode")
    db_url = environ["DATABASE_URL"]
    if environ.get("PROD_DATABASE_URL") == db_url:
        raise ValueError("Refusing to treat production as development")
    return db_url


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--production", action="store_true", help="Use production database")
    parser.add_argument("--execute", action="store_true", help="Fetch and save missing photos")
    parser.add_argument(
        "--confirm-production", action="store_true",
        help="Required with --production --execute to permit production inserts",
    )
    args = parser.parse_args()
    try:
        db_url = choose_database(args, os.environ)
    except (ValueError, KeyError) as exc:
        parser.error(str(exc))

    target = "PRODUCTION" if args.production else "development"
    with closing(psycopg2.connect(db_url, connect_timeout=10)) as conn:
        if not args.execute:
            conn.set_session(readonly=True)
            rows = missing_products(conn)
            print(f"{target} read-only check: {len(rows)} products without photos")
            for product_id, sku, url in rows:
                print(f"Product {product_id}, SKU {sku}: {url}")
            return
        print(f"{target} confirmed photo-only repair", flush=True)
        client = RobustWebClient(status_callback=lambda _message: None)
        repair(conn, client)
    # Verify from a fresh, read-only connection rather than relying on the
    # writer's transaction state.
    with closing(psycopg2.connect(db_url, connect_timeout=10)) as verify_conn:
        verify_conn.set_session(readonly=True)
        still_missing = missing_products(verify_conn)
        print(
            f"Independent {target} verification: "
            f"{len(still_missing)} products still without photos",
            flush=True,
        )


if __name__ == "__main__":
    main()