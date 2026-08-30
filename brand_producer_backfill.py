#!/usr/bin/env python3
"""Rate-limited, resumable backfill of Rimi brand and producer data."""

from __future__ import annotations

import argparse
import json
import os
import time
from typing import Any, Callable, Optional

import psycopg2
from bs4 import BeautifulSoup
from psycopg2.extras import RealDictCursor

from brand_producer import extract_brand_producer, upsert_brand_producer
from robust_web_client import RobustWebClient


PRODUCT_BATCH_QUERY = """
    SELECT product_id, sku, rimi_url
    FROM products
    WHERE product_id > %s
      AND rimi_url IS NOT NULL
      AND BTRIM(rimi_url) <> ''
    ORDER BY product_id
    LIMIT %s
"""


def get_database_url(*, production: bool, confirm_production: bool = False) -> str:
    """Resolve an explicitly selected target with a production write guard."""
    if confirm_production and not production:
        raise ValueError("--confirm-production requires --production.")
    if production and not confirm_production:
        raise ValueError(
            "Production backfill requires --production and --confirm-production."
        )

    if production:
        database_url = os.environ.get("PROD_DATABASE_URL")
        if not database_url:
            raise ValueError("PROD_DATABASE_URL is required for production.")
        development_url = (
            os.environ.get("DATABASE_URL") or os.environ.get("NEON_DATABASE_URL")
        )
        if development_url and development_url == database_url:
            raise ValueError("Development and production database URLs must differ.")
        return database_url

    database_url = os.environ.get("DATABASE_URL") or os.environ.get("NEON_DATABASE_URL")
    if not database_url:
        raise ValueError("DATABASE_URL or NEON_DATABASE_URL is required.")
    return database_url


def backfill_brand_producer(
    connection,
    *,
    limit: Optional[int] = None,
    batch_size: int = 25,
    start_id: int = 0,
    delay_seconds: float = 0.5,
    dry_run: bool = False,
    web_client: Optional[RobustWebClient] = None,
    status_callback: Optional[Callable[[str], None]] = None,
) -> dict[str, Any]:
    """Fetch products in stable ID order and isolate each failure with a savepoint."""
    if limit is not None and limit < 1:
        raise ValueError("limit must be at least 1")
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")
    if start_id < 0:
        raise ValueError("start_id cannot be negative")
    if delay_seconds < 0:
        raise ValueError("delay_seconds cannot be negative")

    status = status_callback or (lambda _message: None)
    client = web_client or RobustWebClient(status)
    processed = 0
    updated = 0
    no_values = 0
    unavailable_pages = 0
    last_id = start_id
    failures: list[dict[str, Any]] = []
    resume_after_product_id = start_id
    cursor_frozen = False

    with connection.cursor(cursor_factory=RealDictCursor) as cursor:
        while limit is None or processed < limit:
            remaining = batch_size if limit is None else min(batch_size, limit - processed)
            cursor.execute(PRODUCT_BATCH_QUERY, (last_id, remaining))
            products = cursor.fetchall()
            if not products:
                break

            for row in products:
                product_id = row["product_id"]
                last_id = product_id
                cursor.execute("SAVEPOINT brand_producer_product")
                try:
                    response = client.fetch_with_retry(row["rimi_url"])
                    if response is None:
                        if getattr(client, "last_fetch_status_code", None) == 404:
                            unavailable_pages += 1
                            cursor.execute("RELEASE SAVEPOINT brand_producer_product")
                            if not cursor_frozen:
                                resume_after_product_id = product_id
                            processed += 1
                            if delay_seconds:
                                time.sleep(delay_seconds)
                            continue
                        raise RuntimeError("Rimi page was unavailable after retries")
                    values = extract_brand_producer(
                        BeautifulSoup(response.text, "html.parser")
                    )
                    if values["brand"] or values["producer"]:
                        if not dry_run:
                            upsert_brand_producer(
                                connection,
                                product_id,
                                brand_name=values["brand"],
                                producer_name=values["producer"],
                                status_callback=status,
                            )
                        updated += 1
                    else:
                        no_values += 1
                    cursor.execute("RELEASE SAVEPOINT brand_producer_product")
                except Exception as exc:
                    cursor_frozen = True
                    cursor.execute("ROLLBACK TO SAVEPOINT brand_producer_product")
                    cursor.execute("RELEASE SAVEPOINT brand_producer_product")
                    failures.append(
                        {
                            "product_id": product_id,
                            "sku": row["sku"],
                            "error": str(exc),
                        }
                    )
                if not cursor_frozen:
                    resume_after_product_id = product_id
                processed += 1
                if delay_seconds:
                    time.sleep(delay_seconds)

            if dry_run:
                connection.rollback()
            else:
                connection.commit()
            status(
                f"Attempted {processed} products "
                f"(last product_id={last_id}, updated={updated}, "
                f"no values={no_values}, failures={len(failures)}, "
                f"unavailable pages={unavailable_pages}, "
                f"safe resume after={resume_after_product_id})"
            )

    return {
        "attempted": processed,
        "updated": updated,
        "no_values": no_values,
        "unavailable_pages": unavailable_pages,
        "failure_count": len(failures),
        "failures": failures,
        "start_id": start_id,
        "last_product_id": last_id,
        "resume_after_product_id": resume_after_product_id,
        "dry_run": dry_run,
    }


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch and store brand/producer data for existing Rimi products."
    )
    parser.add_argument("--production", action="store_true")
    parser.add_argument("--confirm-production", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--batch-size", type=int, default=25)
    parser.add_argument("--start-id", type=int, default=0)
    parser.add_argument("--delay", type=float, default=0.5)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = _parse_args(argv)
    connection = None
    client = None
    try:
        database_url = get_database_url(
            production=args.production,
            confirm_production=args.confirm_production,
        )
        connection = psycopg2.connect(database_url)
        connection.autocommit = False
        client = RobustWebClient(print)
        summary = backfill_brand_producer(
            connection,
            limit=args.limit,
            batch_size=args.batch_size,
            start_id=args.start_id,
            delay_seconds=args.delay,
            dry_run=args.dry_run,
            web_client=client,
            status_callback=print,
        )
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 1 if summary["failure_count"] else 0
    except Exception as exc:
        print(f"Brand/producer backfill failed: {exc}")
        return 2
    finally:
        if client:
            client.close()
        if connection:
            connection.close()


if __name__ == "__main__":
    raise SystemExit(main())