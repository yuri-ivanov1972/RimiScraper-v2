---
name: Rimi price scraping bugs — NULL price crash + HTML structure change
description: Three layered bugs that caused all product price updates to fail silently with "0 successful, N failed".
---

## Bug 1 — NULL price DB crash (lightweight_updater.py)
When a product is out-of-stock on Rimi, no price appears on the listing page.
`_parse_price("")` returns None. The old code did `pass` allowing None to reach the INSERT,
which fails with a NOT NULL constraint violation on `product_price_history.price`.
The exception is caught silently; no record is written; DB availability stays frozen.

**Fix:** After fetching `old_price` from the DB, if `price is None and not is_available`,
set `price = old_price if old_price is not None else 0.0` before the INSERT.

## Bug 2 — Rimi HTML structure changed (core_parser.py)
Rimi updated their price HTML to use `<span aria-hidden="true">` for visible digits
and `<span class="sr-only">` for the full text "1.45 € par gab.".
The parser was selecting the sr-only span first, building garbage like "€1.45 €par gab."
which `_parse_price()` cannot convert → returns None → all 13 updates fail.

Also: `re.match` for price-per-unit fails because sr-only text ("Cena par vienību:...")
precedes the number in the concatenated text. Fixed with `re.search`.

**Fix (core_parser.py, extract_products_from_page):**
- Price extraction: `price_tag.find('span', attrs={'aria-hidden': 'true'})` first, fall back to any span
- price_per_unit: prefer aria-hidden span; `re.match` → `re.search`
- discount_price_per_unit: same pattern

**Why:** Rimi added sr-only accessibility text around prices. Future Rimi HTML changes
should be checked against this aria-hidden pattern first.

## Bug 3 — Silent errors (batch_processor.py)
Error messages from `LightweightUpdater.batch_update_from_listing()` were collected in
`update_results['errors']` but never logged, making the root cause invisible in worker logs.

**Fix:** Added a log line per error: `self.status_callback(f"❌ SKU {sku} failed: {error}")`.

## Sanity check added (batch_processor.py)
If 100% of scraped products in a category come back as unavailable, treat it as a likely
geo-block or scrape failure and skip writing to DB (preserve last known state).
Log: "⚠️ All N products returned as unavailable — possible geo-block or scrape failure."

## Request headers (core_parser.py)
Changed Accept-Language from `en-US` to `lv-LV,lv;q=0.9` and User-Agent to Chrome/125
to avoid Rimi geo-restricting content for North American IPs.
