---
name: Nutrition validation rollout
description: Scope and evidence boundaries for ingredient/nutrition consistency checks.
---

The initial nutrition-consistency backfill was reviewed on 2026-08-29. Its schema is approved for the production deployment startup migration without changing the reviewed keyword groups, weights, or thresholds. Do not automatically run validation after scraping; that integration remains separate work.

**Why:** Two complete development backfills produced identical distributions with no failures. Frequent high/medium findings were explainable contradictions; isolated contextual and rounding cases did not justify weakening broad rules.

**How to apply:** Treat parsed ingredient mappings as the source of ingredient identity. Raw ingredient labels may recover explicit percentages and advisory-clause context, but must not introduce separate ingredient identities or modify source nutrition data. Deployment startup may apply and verify the additive schema migration; production backfill and scrape-time execution require their own rollout steps.