# Maxima Product Scraper Project

## Project Overview
Create a web scraper for Maxima grocery store (Latvia) that extracts product data, calculates Nutri-Score using the official 2024 algorithm, and stores results in a PostgreSQL database.

## Core Requirement: Nutri-Score 2024 Algorithm
Use the provided `nutriscore_calculator.py` file - it contains the complete, verified implementation of the official 2024 Nutri-Score algorithm.

---

## Nutri-Score Calculator Usage

### Quick Start
```python
from nutriscore_calculator import NutriscoreCalculator

calculator = NutriscoreCalculator()

result = calculator.calculate_single_product(
    energy_kj=1604,
    sugars=8.0,
    saturated_fat=0.2,
    salt=1.1,
    protein=7.0,
    fiber=5.0,
    category_code="YOUR_MAXIMA_CATEGORY_CODE",
    product_name="Product Name",
    ingredients_text="Ingredients list for sweetener detection"
)

print(f"Grade: {result['grade']}, Score: {result['score']}")
```

### Important: Category Mapping Required
The calculator uses **Rimi category codes** (SH-X-X-X format) for category detection. For Maxima, you need to:

1. Map Maxima categories → Nutri-Score categories manually, OR
2. Create a mapping function that converts Maxima categories to one of:
   - `'general'` - Default for most foods
   - `'beverage'` - Drinks, juices, milk
   - `'red_meat'` - Meat products (protein capped at 2 points)
   - `'cheese'` - Cheese products (exempt from protein block)
   - `'fats_oils_nuts'` - Oils, butter, margarine, nuts

### Direct Category Specification
You can bypass category code detection by determining the category yourself:

```python
from nutriscore_calculator import calculate_nutriscore_2024

result = calculate_nutriscore_2024(
    category='general',  # 'general', 'beverage', 'red_meat', 'cheese', 'fats_oils_nuts'
    energy_kj=1604,
    sugars_g=8.0,
    sat_fat_g=0.2,
    salt_g=1.1,
    protein_g=7.0,
    fiber_g=5.0,
    fvl_pct=0,  # Fruits/vegetables/legumes percentage (0-100)
    total_fat_g=2.5,  # Required for fats_oils_nuts category
    has_sweeteners=False  # For beverages: artificial sweetener penalty
)

print(f"Grade: {result['grade']}, Score: {result['score']}")
```

---

## Algorithm Details (Verified & Tested)

### 5 Product Categories
| Category | Key Rules |
|----------|-----------|
| **General** | Standard thresholds, protein block rule applies |
| **Beverage** | Stricter thresholds, water=A, +4 sweetener penalty |
| **Red Meat** | Protein capped at max 2 points |
| **Cheese** | Exempt from protein block rule |
| **Fats/Oils/Nuts** | Uses energy from saturated fat, sat/fat ratio |

### Critical Rule: Protein Block
**When N ≥ 11 AND FVL points < 5**: Protein is excluded from positive points.
- Applies to: general, red_meat, fats_oils_nuts
- Does NOT apply to: cheese, beverages

### Thresholds (per 100g unless beverage)

**Negative Points (N):**
| Nutrient | Max Points | General Thresholds | Beverage Thresholds |
|----------|------------|-------------------|---------------------|
| Energy | 10 | 335-3350 kJ | 0-270 kJ |
| Sugar | 15 | 3.4-51g | 0-10g |
| Sat Fat | 10 | 1-10g | Same as general |
| Salt | 20 | 0.2-4g | 0.05-1g |
| Sweeteners | 4 | N/A | +4 if artificial sweeteners |

**Positive Points (P):**
| Nutrient | Max Points | Thresholds |
|----------|------------|------------|
| Fiber | 5 | 0.7-3.5g |
| Protein | 7 | 1.2-8.4g (general), 1.2-6.6g (beverage) |
| FVL | 5 | 40/60/80% (5 pts at 80%+) |

### Grade Thresholds
| Grade | General Foods | Beverages | Fats/Oils/Nuts |
|-------|---------------|-----------|----------------|
| A | ≤ -1 | Water only | ≤ -6 |
| B | ≤ 2 | ≤ 2 | ≤ 2 |
| C | ≤ 10 | ≤ 6 | ≤ 10 |
| D | ≤ 18 | ≤ 9 | ≤ 18 |
| E | > 18 | > 9 | > 18 |

---

## Database Schema

### Core Tables

```sql
CREATE TABLE products (
    product_id SERIAL PRIMARY KEY,
    sku VARCHAR(50) UNIQUE NOT NULL,
    name VARCHAR(500) NOT NULL,
    name_norm VARCHAR(500),  -- Normalized lowercase name
    maxima_url VARCHAR(1000),
    category_id INTEGER REFERENCES categories(category_id),
    quantity_value DECIMAL(10,3),
    quantity_unit VARCHAR(20),
    country_of_origin VARCHAR(100),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE nutritionfacts (
    nutrition_id SERIAL PRIMARY KEY,
    product_id INTEGER UNIQUE REFERENCES products(product_id),
    energy_kj DECIMAL(10,2),
    energy_kcal DECIMAL(10,2),
    fat DECIMAL(10,2),
    fat_saturated DECIMAL(10,2),
    carbs DECIMAL(10,2),
    carbs_sugars DECIMAL(10,2),
    protein DECIMAL(10,2),
    salt DECIMAL(10,3),
    fiber DECIMAL(10,2),
    nutri_score_grade CHAR(1),
    nutri_score_points INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE categories (
    category_id SERIAL PRIMARY KEY,
    maxima_category_code VARCHAR(50) UNIQUE,
    name_lv VARCHAR(200),
    name_en VARCHAR(200),
    parent_category_id INTEGER REFERENCES categories(category_id),
    nutriscore_category VARCHAR(20) DEFAULT 'general',  -- Maps to NS category
    fvl_percentage INTEGER DEFAULT 0
);

CREATE TABLE product_price_history (
    price_history_id SERIAL PRIMARY KEY,
    product_id INTEGER REFERENCES products(product_id),
    price DECIMAL(10,2),
    currency VARCHAR(3) DEFAULT 'EUR',
    is_available BOOLEAN DEFAULT TRUE,
    recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    discount_price DECIMAL(10,2),
    price_per_unit DECIMAL(10,2),
    price_per_unit_type VARCHAR(20)
);

CREATE TABLE ingredients (
    ingredient_id SERIAL PRIMARY KEY,
    product_id INTEGER REFERENCES products(product_id),
    ingredients_text TEXT,
    allergens TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE product_additives (
    id SERIAL PRIMARY KEY,
    product_id INTEGER REFERENCES products(product_id),
    additive_code VARCHAR(10),  -- E-number
    additive_name VARCHAR(200),
    UNIQUE(product_id, additive_code)
);
```

---

## Key Implementation Notes

### 1. Category Mapping for Maxima
Create a mapping table or function that assigns each Maxima category to:
- `nutriscore_category`: 'general', 'beverage', 'red_meat', 'cheese', 'fats_oils_nuts'
- `fvl_percentage`: 0, 50, or 100

Example approach:
```python
MAXIMA_TO_NUTRISCORE = {
    'drinks/juices': ('beverage', 0),
    'drinks/milk': ('beverage', 0),
    'meat/sausages': ('red_meat', 0),
    'meat/fresh': ('red_meat', 0),
    'dairy/cheese': ('cheese', 0),
    'oils-fats/butter': ('fats_oils_nuts', 0),
    'oils-fats/oils': ('fats_oils_nuts', 0),
    'fruits-vegetables/fresh': ('general', 100),
    'fruits-vegetables/canned': ('general', 50),
    # ... etc
}
```

### 2. Sweetener Detection
The calculator includes automatic sweetener detection for beverages using:
- Latvian ingredient keywords (aspartāms, sukraloze, etc.)
- E-numbers (E950-E969)
- Marketing terms (zero, light, diet, bez cukura)

If you have ingredients text, pass it to enable detection:
```python
result = calculator.calculate_single_product(
    ...,
    product_name="Coca-Cola Zero",
    ingredients_text="water, aspartāms, ..."  # Will detect sweeteners
)
```

### 3. Fiber Handling
If fiber is missing from nutrition data:
- Default to 0 (safe, results in lower P points)
- Or implement category-based estimation (higher fiber for cereals, grains, etc.)

### 4. Price History Pattern
Store prices in history table, not products table:
```python
# Wrong: UPDATE products SET price = 1.99
# Correct: INSERT INTO product_price_history (product_id, price, ...) VALUES (...)
```

---

## Scraper Implementation Checklist

1. [ ] Parse Maxima category structure
2. [ ] Map Maxima categories → Nutri-Score categories
3. [ ] Extract product data: name, SKU, URL, price
4. [ ] Extract nutrition facts (energy, fat, sat fat, carbs, sugars, protein, salt, fiber)
5. [ ] Extract ingredients text
6. [ ] Calculate Nutri-Score using provided calculator
7. [ ] Store in database with proper normalization
8. [ ] Handle pagination and rate limiting
9. [ ] Implement incremental updates (check existing SKUs)

---

## Testing the Calculator

```python
# Test case: Breakfast cereal
result = calculate_nutriscore_2024(
    category='general',
    energy_kj=1604,
    sugars_g=8.0,
    sat_fat_g=0.2,
    salt_g=1.1,
    protein_g=7.0,
    fiber_g=5.0,
    fvl_pct=0
)
# Expected: Grade C, Score 6, Protein blocked (N=11, FVL=0)

# Test case: Water
result = calculate_nutriscore_2024(
    category='beverage',
    energy_kj=0,
    sugars_g=0,
    sat_fat_g=0,
    salt_g=0,
    protein_g=0,
    fiber_g=0,
    fvl_pct=0,
    has_sweeteners=False
)
# Expected: Grade A (water rule)

# Test case: Zero sugar soda
result = calculate_nutriscore_2024(
    category='beverage',
    energy_kj=5,
    sugars_g=0,
    sat_fat_g=0,
    salt_g=0.02,
    protein_g=0,
    fiber_g=0,
    fvl_pct=0,
    has_sweeteners=True  # +4 penalty
)
# Expected: Grade C or D (sweetener penalty)
```

---

## Files Provided

1. **nutriscore_calculator.py** - Complete 2024 algorithm with:
   - `NutriscoreCalculator` class for easy integration
   - `calculate_nutriscore_2024()` function for direct use
   - Category detection (Rimi codes - needs Maxima mapping)
   - Sweetener detection (Latvian + English)
   - All 5 category calculations
   - Verified thresholds and grade boundaries

---

## Quick Reference: Algorithm Formula

```
Final Score = N - P

Where:
N = energy_pts + sugar_pts + satfat_pts + salt_pts [+ sweetener_pts for beverages]
P = protein_pts + fiber_pts + fvl_pts

Special rules:
- Red meat: protein_pts = min(protein_pts, 2)
- Protein block: if N >= 11 AND fvl_pts < 5, exclude protein from P
- Cheese: exempt from protein block
- Beverages: water with no sweeteners = automatic A
```
