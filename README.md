# RimiScraper-v2

Crawls the [Rimi](https://www.rimi.lv) Latvia online store and parses product data into PostgreSQL. This repository is one of the two data sources for [abcde.lv](https://abcde.lv); the other is [BarboraScraper-v1](https://github.com/yuri-ivanov1972/BarboraScraper-v1), which covers Maxima.

## What it does

- **Scrapes products**: name, SKU, price, photos, quantity (including multipack patterns such as `25x2g`), country of origin, ingredients and nutrition values. Retry logic is in `robust_web_client.py`.
- **Tracks prices**: each price or availability change is inserted as a new row in `product_price_history`. The `products` table holds product metadata only.
- **Scores products**:
  - Nutri-Score using the 2024 algorithm (`nutriscore_calculator.py`)
  - NOVA processing level (`nova_calculator.py`)
  - Fiber estimates (`fiber_estimator.py`)
  - Missing nutrition filled from USDA data (`usda_enrichment.py`)
  - Nutrition validation (`nutrition_validator.py`)
- **Analyzes ingredients**: finds E-number additives and makes one AI pass (OpenAI/Gemini) to classify each ingredient as natural, processed or uncategorized and flag suspicious ones (`combined_ingredient_analyzer.py`).
- **Records brands and producers** in `brand_producer.py`.

## Architecture

| Component | Entry point | Role |
|---|---|---|
| Streamlit UI | `main.py` | Product search, viewing, reports, queueing category jobs |
| Worker | `worker.py` | Background category processing from a PostgreSQL job queue with heartbeats and stale-job reassignment |
| Scheduler | `auto_update.py`, `worker_with_scheduler.py` | Queues categories for the daily price and availability updates |
| Combined startup | `combined_startup.sh` | Runs the UI and the worker together, restarting them when they crash |

The project was built on Replit and is configured there by `.replit` and `replit.nix`.

## Setup

Requires Python 3.11 or newer and PostgreSQL. Dependencies are managed with [uv](https://github.com/astral-sh/uv):

```bash
uv sync
```

Environment variables used by the code:

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | Main PostgreSQL connection |
| `PROD_DATABASE_URL` | Production database (migration and sync scripts) |
| `PRODUCTS_DB_URL`, `CATEGORIES_DB_URL`, `NEON_DATABASE_URL` | Additional database connections used by some modules |
| `AI_INTEGRATIONS_GEMINI_API_KEY`, `AI_INTEGRATIONS_GEMINI_BASE_URL` | Gemini access for ingredient analysis |
| `USDA_API_KEY` | USDA nutrition enrichment |
| `GOOGLE_TRANSLATE_API_KEY` | Food name translation |

To initialize the database, run `schema.sql` (or `init_database.py`) and then the numbered files in `migrations/`.

## Running

```bash
# UI
streamlit run main.py --server.port 5000

# Worker daemon
python worker.py --daemon --chunk-size 15 --max-workers 3 --heartbeat-interval 30

# Queue every category, then process the queue
python auto_update.py --queue-all --priority 5
python worker.py --resume-all

# UI and worker together, with auto-restart
./combined_startup.sh
```

## Tests

The tests are the `test_*.py` files in the repository root:

```bash
uv run pytest
```

Many of them read or write a real database, so check what a test touches before pointing it at production.

## Further documentation

- `replit.md`: full architecture notes and schema facts
- `WORKER_USAGE.md`: worker CLI and job queue
- `DAILY_UPDATES_GUIDE.md`: scheduled updates
- `DATABASE_SETUP.md`, `MIGRATION_GUIDE.md`: database setup and migration
- `RESERVED_VM_SETUP.md`: deployment
- `NUTRITION_VALIDATION_REVIEW.md`, `BRAND_PRODUCER_REVIEW.md`, `PRODUCT_PERCENTAGE_ROLLOUT.md`: feature notes
