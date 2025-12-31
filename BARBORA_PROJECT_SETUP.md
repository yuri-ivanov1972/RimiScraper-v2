# Barbora Product Scraper - New Project Setup Guide

This document contains everything needed to set up the new Barbora.lv product scraper project remixed from the Rimi scraper.

## 1. Secrets to Create

After remixing the project, create the following secrets in the Replit Secrets tab:

### Required Secrets

| Secret Name | Description | How to Get |
|-------------|-------------|------------|
| `DATABASE_URL` | Development PostgreSQL connection string | Auto-created when you create a PostgreSQL database in the new project |
| `PGDATABASE` | Database name | Auto-created with PostgreSQL |
| `PGHOST` | Database host | Auto-created with PostgreSQL |
| `PGPORT` | Database port | Auto-created with PostgreSQL |
| `PGUSER` | Database user | Auto-created with PostgreSQL |
| `PGPASSWORD` | Database password | Auto-created with PostgreSQL |
| `PROD_DATABASE_URL` | Production PostgreSQL connection string | Create production database and copy connection string |

### Optional Secrets

| Secret Name | Description | How to Get |
|-------------|-------------|------------|
| `USDA_API_KEY` | USDA FoodData Central API key for nutrition enrichment | Register at https://fdc.nal.usda.gov/api-key-signup.html |
| `SESSION_SECRET` | Session encryption key for Streamlit | Generate random string |

## 2. Database Setup

### Step 1: Create PostgreSQL Database
In the new Barbora project, use the "Create PostgreSQL database" option in Replit. This will auto-populate the DATABASE_URL and PG* secrets.

### Step 2: Run Schema Creation
After database is created, run the schema file to create all tables:

```bash
psql $DATABASE_URL -f barbora_schema.sql
```

Or copy the contents of `barbora_schema.sql` and run in the SQL tool.

## 3. Code Changes Summary

After schema is created, make these code adaptations:

### File Renames/Changes Needed

1. **core_parser.py** → Adapt for Barbora HTML structure
   - Change `RimiParser` to `BarboraParser`
   - Update URL patterns from `rimi.lv` to `barbora.lv`
   - Parse GA4 JSON for product data extraction
   - Adapt price selectors for Barbora layout

2. **Database field references**
   - Change `rimi_category_code` → `barbora_category_code`
   - Change `rimi_url` → `barbora_url`

3. **Lightweight Updater**
   - Adapt listing page selectors for Barbora cards
   - Update PALDIES price parsing (similar to MansRimi)

4. **Streamlit UI**
   - Change all "Rimi" labels to "Barbora"
   - Update category browser for Barbora hierarchy

## 4. Barbora-Specific Data Extraction

### Product Data from GA4 JSON
Extract from `<script>` containing `window.reportUserActionToGa4`:

```javascript
{
    "item_id": "000000000000844077",  // Use as SKU
    "item_name": "Siers DŽIUGAS Delicate 40% 24 mēn. 180g",
    "currency": "eur",
    "item_brand": "Džiugas",
    "item_category": "Piena produkti un olas",   // Level 1
    "item_category2": "Siers",                    // Level 2
    "item_category3": "Cietais siers",            // Level 3
    "price": 3.83,
    "discount": 0.0
}
```

### Nutrition Table
Same structure as Rimi - parse from `Uzturvērtība (100 g/ml)` section

### Price Selectors (from product page)
- Regular price: In product info section (euros + cents format)
- PALDIES price: Loyalty card discount price
- Price per unit: From "€/kg" or "€/l" text

### Photo URLs
From Barbora CDN: `https://cdn.barbora.lv/products/{uuid}_m.png`

## 5. Category Import

User has the Barbora category list ready. Structure:
- Level 1: Main categories (e.g., "Piena produkti un olas")
- Level 2: Subcategories (e.g., "Siers")
- Level 3: Product groups (e.g., "Cietais siers")

Import format matches normalized_categories table.

## 6. Worker Configuration

Same as Rimi project:
- Daily queue at 2:00 AM Latvia time
- Daily report at 6:00 AM Latvia time
- Reserved VM deployment recommended ($20/month)
- Worker settings: `--chunk-size 15 --max-workers 3`

## 7. Project Goals

This project supports https://abcde.lv initiative to make Nutri-Score mandatory on all grocery products in Latvia. Barbora data complements Rimi data for comprehensive market coverage.

Future: Category matching between Rimi and Barbora for price comparison features.
