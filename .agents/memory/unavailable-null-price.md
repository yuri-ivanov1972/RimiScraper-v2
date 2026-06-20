---
name: Unavailable product NULL price bug
description: lightweight_updater.py crashes silently when a product is out-of-stock and has no price on the listing page, causing all price updates to show "0 successful, N failed".
---

## The Rule
After fetching `old_price` from the DB in `update_from_listing_data`, if `price is None and not is_available`, set `price = old_price if old_price is not None else 0.0` before the INSERT. Never attempt to INSERT NULL into `product_price_history.price` — the column is NOT NULL.

**Why:** When a product is out-of-stock on Rimi, no price is rendered on the listing page. `_parse_price("")` returns None. The old code did `pass` allowing None to reach the INSERT, which fails with a DB constraint violation. The exception is caught silently, the record is never written, and DB availability stays frozen at the last successful scrape (potentially months ago).

**How to apply:** The fix lives at lines ~142-143 of `lightweight_updater.py`, after `old_price` is resolved from the DB. Categories most at risk are those with many out-of-stock products (SH-7-2-15 78%, SH-7-1-11 41%, egg categories 100%).
