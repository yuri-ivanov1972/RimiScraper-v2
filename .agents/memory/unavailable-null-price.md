---
name: Unavailable product NULL price bug + geo-block false negatives
description: Two related scraping issues causing price update failures and incorrect unavailability records for Rimi products.
---

## Issue 1 — NULL price DB crash (fixed in lightweight_updater.py)
When a product is out-of-stock on Rimi, no price appears on the listing page.
`_parse_price("")` returns None. The old code did `pass` allowing None to reach the INSERT,
which fails with a NOT NULL constraint violation on `product_price_history.price`.
The exception is caught silently; no record is written; DB availability stays frozen.

**Fix:** After fetching `old_price` from the DB, if `price is None and not is_available`,
set `price = old_price if old_price is not None else 0.0` before the INSERT.

## Issue 2 — Geo-block causes false "all unavailable" (fixed in core_parser.py + batch_processor.py)
Rimi serves different content to North American IPs with `Accept-Language: en-US`.
The `.js-open-similar-products` button appeared for ALL products, marking them unavailable
even though they were genuinely in stock.

**Fix A — Headers:** Changed `Accept-Language` to `lv-LV,lv;q=0.9,en;q=0.8`, updated
User-Agent to Chrome/125, added `Referer: https://www.rimi.lv/`.

**Fix B — Sanity check:** If 100% of scraped products are unavailable, skip DB writes
(treat as scrape failure, preserve last known state).

**Fix C — Availability detection:** Changed from single condition (`.js-open-similar-products`)
to dual condition (button present AND no price). A product with a valid price is always available.

**Why:** NA IP + en-US locale → Rimi geo-restricted response → all products show "similar products"
button instead of "add to cart" → scraper marks all as unavailable → NULL price INSERT → crash.
