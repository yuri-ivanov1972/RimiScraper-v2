---
name: Nutrition validation rollout
description: Scope and evidence boundaries for ingredient/nutrition consistency checks.
---

The first nutrition-consistency rollout is a development-only backfill that stores one current result per product. Do not automatically run it after scraping or apply it to production until development findings have been reviewed.

**Why:** The rule weights and Latvian keyword groups need real-data review before they affect continuously updated or production datasets.

**How to apply:** Treat parsed ingredient mappings as the source of ingredient identity. Raw ingredient labels may recover explicit percentages and advisory-clause context, but must not introduce separate ingredient identities or modify source nutrition data.