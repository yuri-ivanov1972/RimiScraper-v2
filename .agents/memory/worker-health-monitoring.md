---
name: Worker health monitoring — alarm system
description: Why silent zero-progress worker runs went unnoticed for 3 months, and the 4-task alarm system built to prevent recurrence.
---

## Why the problem went unnoticed
- `update_statistics` table existed but was never written to — always empty.
- `daily_update_logs` had one test record only — not used by worker.
- `job_events` metadata column was always null for completed jobs — no quality data stored.
- Jobs marked `completed` regardless of 0 successful updates — no quality gate.
- Streamlit "Changes" panel showed 0 price changes but no alert was raised.
- Last real `lightweight_update` records: Feb 22, 2026. Last `rimi_scraper` records: Mar 29, 2026.
  After that, ~3 months of silent zero-progress runs until Jun 2026.

## 4-task alarm system (implemented Jun 2026)

### Task 1 — Job-level alarm (batch_processor.py)
`_write_alarm_event()` helper writes `price_update_alarm` to `job_events` when `successful == 0 and failed > 0`.
Emits a loud `🚨 ALARM` log line visible immediately in worker output.

### Task 2 — Populate update_statistics (worker.py)
`_record_update_statistics()` inserts one row per completed job into `update_statistics`
with: job_id, category_code, total_checked, new_products, price_changed, data_updated, unchanged, failed.

### Task 3 — Price-drought global banner (main.py)
`_get_drought_status()` queries max recorded_at and recent price_changed sum.
If days_stale >= 7 OR recent_price_changes_7d == 0 → `is_drought = True`.
Banner shown on every page in `main()` via session_state cache (one DB query per session).

### Task 4 — Worker Health panel (main.py, section_worker_health)
New "🔔 Health" nav button (shows "🔔 Health 🚨" when drought active).
Panel shows:
- Price data freshness (% updated in 7/30/90 days)
- Recent price_update_alarm events with expandable error details
- Recent job results table from update_statistics (success rate per job)
- Per-category staleness table (colour-coded: red >= 90 days, yellow >= 30 days)

**Why:** Grocery prices change daily — 0 price changes for a week is a guaranteed sign something is broken.
Alarm fires immediately on the next worker run instead of waiting months for manual discovery.
