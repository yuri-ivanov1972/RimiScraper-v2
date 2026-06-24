---
name: Product-level NOVA classification
description: How per-product NOVA scores are calculated and stored.
---

## Storage
Two columns added to `products` table:
- `nova_score` integer (1–4)
- `nova_source` varchar(30): `'additive_override'` or `'category_inherited'`

## Rule (in priority order)
1. **Additive override** — if any ingredient mapped to the product has `suspicion_level IN ('avoid', 'limit')` in `ingredient_analysis` → `nova_score = 4`, `nova_source = 'additive_override'`
2. **Category fallback** — otherwise, inherit `nova_score` from `normalized_categories` via `category_id` → `nova_source = 'category_inherited'`
3. Products with no ingredient data also use category fallback.

`caution` level does NOT trigger NOVA 4 (user decision — too broad, would hit 68% of products).

## Final distribution (Jun 2026, 2966 products)
- NOVA 1 category_inherited: 498
- NOVA 2 category_inherited: 1
- NOVA 3 category_inherited: 855
- NOVA 4 additive_override: 1486
- NOVA 4 category_inherited: 126
- NULL: 0

## Join key
`ingredient_product_mapping` uses `product_sku` (text), NOT `product_id`.

## Re-running
The population script is embedded inline (not a standalone file). To re-run:
1. Pass A: UPDATE products SET nova_score=4, nova_source='additive_override' WHERE EXISTS (ipm+ia join with suspicion_level IN ('avoid','limit'))
2. Pass B: UPDATE remaining NULL products from normalized_categories nova_score

**Why:** Category NOVA alone misclassifies products that contain industrial additives; ingredient-level override catches ultra-processed products that happen to sit in a low-NOVA category.
