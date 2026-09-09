---
name: Nutrition validation rollout
description: Scope and evidence boundaries for ingredient/nutrition consistency checks.
---

Nutrition validation is intentionally limited to three direct ingredient/value contradictions, joined by OR: sugar with sugars unreported, salt with salt unreported, or dairy with saturated fat unreported. Unreported means missing, blank, or non-positive.

**Why:** The results are shared externally with Rimi, so false-positive avoidance is more important than detecting broader mathematical, energy, ingredient-association, or zero-cluster anomalies.

**How to apply:** Treat parsed ingredient mappings as the source of identity. Raw labels may recover percentage and advisory context. Weak/advisory and explicitly tiny evidence must not trigger a finding. Recalculate stored validation rows after rule changes.