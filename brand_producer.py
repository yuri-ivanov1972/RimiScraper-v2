"""Rimi brand and producer extraction plus normalized entity persistence."""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Any, Callable, Dict, Optional

from bs4 import BeautifulSoup


def normalize_entity_name(value: Any) -> Optional[str]:
    """Return a stable matching key, or None for an empty/missing value."""
    if value is None:
        return None
    cleaned = unicodedata.normalize("NFKC", str(value))
    cleaned = " ".join(cleaned.split()).strip()
    if not cleaned:
        return None
    return cleaned.casefold()


def canonical_entity_name(value: Any) -> Optional[str]:
    """Keep a readable source value while normalizing Unicode and whitespace."""
    if value is None:
        return None
    cleaned = unicodedata.normalize("NFC", str(value))
    cleaned = " ".join(cleaned.split()).strip()
    return cleaned or None


def extract_details_html(soup: BeautifulSoup) -> Optional[str]:
    """Decode the details-tab HTML embedded in Storefront.product_details_page."""
    for script in soup.find_all("script"):
        script_content = script.string or script.get_text()
        if not script_content or "Storefront.product_details_page" not in script_content:
            continue

        match = re.search(
            r'identifier:\s*["\']details["\'],[^}]*html:\s*"((?:[^"\\]|\\.)*)"',
            script_content,
            re.DOTALL,
        )
        if not match:
            match = re.search(
                r'html:\s*"((?:[^"\\]|\\.)*)".*?identifier:\s*["\']details["\']',
                script_content,
                re.DOTALL,
            )
        if not match:
            continue

        encoded_html = match.group(1)
        try:
            return json.loads(f'"{encoded_html}"')
        except json.JSONDecodeError:
            # Rimi has historically emitted a few non-JSON JavaScript escapes.
            return (
                encoded_html.replace("\\/", "/")
                .replace('\\"', '"')
                .replace("\\n", "\n")
                .replace("\\t", "\t")
                .replace("\\r", "\r")
            )
    return None


def _extract_labeled_value(details_soup: BeautifulSoup, label: str) -> Optional[str]:
    """Extract a value from Rimi's label -> div.text -> p structure."""
    for span in details_soup.find_all("span"):
        if " ".join(span.get_text(" ", strip=True).split()).casefold() != label.casefold():
            continue
        item = span.find_parent("li", class_="item") or span.parent
        if not item:
            continue
        text_node = item.find("div", class_="text")
        if text_node:
            value = canonical_entity_name(text_node.get_text(" ", strip=True))
            if value:
                return value
    return None


def extract_brand_producer(soup: BeautifulSoup) -> Dict[str, Optional[str]]:
    """Extract independent brand and producer values from a Rimi product page."""
    details_html = extract_details_html(soup)
    if not details_html:
        return {"brand": None, "producer": None}

    details_soup = BeautifulSoup(details_html, "html.parser")
    return {
        "brand": _extract_labeled_value(details_soup, "Zīmols"),
        "producer": _extract_labeled_value(details_soup, "Ražotājs"),
    }


def upsert_brand_producer(
    connection,
    product_id: int,
    *,
    brand_name: Any = None,
    producer_name: Any = None,
    status_callback: Optional[Callable[[str], None]] = None,
) -> Dict[str, Optional[int]]:
    """
    Upsert supplied master entities and attach them to a product.

    Missing values are intentionally ignored, preserving an existing foreign key.
    Existing canonical names and website URLs are never overwritten.
    """
    status = status_callback or (lambda _message: None)
    brand = canonical_entity_name(brand_name)
    producer = canonical_entity_name(producer_name)
    brand_key = normalize_entity_name(brand)
    producer_key = normalize_entity_name(producer)
    result: Dict[str, Optional[int]] = {"brand_id": None, "producer_id": None}

    def returned_id(row: Any, key: str) -> int:
        return row[key] if isinstance(row, dict) else row[0]

    with connection.cursor() as cursor:
        if brand_key:
            cursor.execute(
                """
                INSERT INTO brands (name, normalized_name)
                VALUES (%s, %s)
                ON CONFLICT (normalized_name) DO UPDATE
                    SET updated_at = CURRENT_TIMESTAMP
                RETURNING brand_id
                """,
                (brand, brand_key),
            )
            result["brand_id"] = returned_id(cursor.fetchone(), "brand_id")

        if producer_key:
            cursor.execute(
                """
                INSERT INTO producers (name, normalized_name)
                VALUES (%s, %s)
                ON CONFLICT (normalized_name) DO UPDATE
                    SET updated_at = CURRENT_TIMESTAMP
                RETURNING producer_id
                """,
                (producer, producer_key),
            )
            result["producer_id"] = returned_id(cursor.fetchone(), "producer_id")

        updates = []
        values = []
        if result["brand_id"] is not None:
            updates.append("brand_id = %s")
            values.append(result["brand_id"])
        if result["producer_id"] is not None:
            updates.append("producer_id = %s")
            values.append(result["producer_id"])

        if updates:
            values.append(product_id)
            cursor.execute(
                f"""
                UPDATE products
                SET {", ".join(updates)}, updated_at = CURRENT_TIMESTAMP
                WHERE product_id = %s
                """,
                tuple(values),
            )

        if result["brand_id"] is not None and result["producer_id"] is not None:
            cursor.execute(
                """
                INSERT INTO brand_producers (brand_id, producer_id)
                VALUES (%s, %s)
                ON CONFLICT (brand_id, producer_id) DO NOTHING
                """,
                (result["brand_id"], result["producer_id"]),
            )

    if brand:
        status(f"Saved brand: {brand}")
    if producer:
        status(f"Saved producer: {producer}")
    return result