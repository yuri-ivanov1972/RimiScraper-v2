---
name: Nutri-Score category typing
description: The authoritative source and runtime rules for category-specific Nutri-Score scoring.
---

Nutri-Score classification for a database product must use its saved normalized-category type, not a product category code or a duplicate source-code list. A category ID and the caller's active database connection are required; an unreviewed NULL type means General.

**Why:** Category-specific scoring is editorial data maintained through the category type editor. Hardcoded codes silently diverge from that editorial decision and prevent explicit overrides from taking effect.

**How to apply:** Any new product scoring path must pass `category_id` plus its current database connection to the calculator. Treat missing categories, invalid types, and lookup failures as clear calculation errors rather than falling back to a guessed type.