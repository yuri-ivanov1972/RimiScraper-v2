# Rimi Product Scraper

## Overview
This Streamlit web application scrapes product data from Rimi to analyze food additives (E-numbers) and nutritional content. It extracts product information, nutritional data, and identifies potentially harmful food additives, storing the data in a PostgreSQL database. The project aims to provide comprehensive insights into product composition and additive content, supporting detailed analysis and reporting.

## User Preferences
Preferred communication style: Simple, everyday language.
Preferred approach: Simplified category-by-category analysis in read-only mode without database modifications.

**CRITICAL DEVELOPMENT RULE**: Always check existing database schema FIRST before making any assumptions about table names, field names, or database structure. Use SQL queries to verify actual schema before writing code that references database tables/columns.

**CRITICAL SCHEMA FACTS** (verified from production database):
- **products table** does NOT have `price` or `is_available` columns
- **product_price_history table** stores ALL price and availability data with columns: `price_history_id`, `product_id`, `price`, `currency`, `is_available`, `recorded_at`, `data_source`, `created_at`, `price_per_unit`, `price_per_unit_type`, `discount_price`, `discount_price_per_unit`
- To get current price/availability: Query latest record from `product_price_history` using LATERAL JOIN
- To update price/availability: INSERT new record into `product_price_history` (do NOT UPDATE products table)
- Products table only tracks: `product_id`, `sku`, `name`, `name_norm`, `rimi_url`, `category_id`, `quantity_value`, `quantity_unit`, `created_at`, `updated_at`, `country_of_origin`, `nutrition_source`, `needs_enrichment`, `enrichment_reviewed`

**CRITICAL COMMUNICATION RULE**: NEVER invent, assume, or imagine facts, data, category names, product information, or system details. When you don't know something factual about the system, Rimi categories, product data, or any other concrete information:
1. Explicitly state "I don't know" or "I need to check"  
2. Ask the user directly for the correct information
3. Use available tools to verify facts from actual data sources
4. Do not provide examples or suggestions based on assumptions
5. Do not create placeholder lists or fictional category mappings

## System Architecture

### Deployment Architecture
The system uses a dual deployment strategy:
- **Streamlit UI**: Deployed on an autoscale environment for on-demand access.
- **Worker System**: Designed for a reserved VM to handle 24/7 background processing and daily updates, optimizing costs. Currently, a temporary autoscale workaround is in place for the worker.

### Application Architecture
The application features a modular Python architecture:
- **Frontend**: Streamlit for the user interface and job queueing.
- **Worker System**: A standalone CLI worker (`worker.py`) for background category processing, independent of Streamlit.
- **Job Queue**: PostgreSQL-based job queue with worker registration, heartbeat monitoring, and stale job reassignment.
- **Backend**: Python modules for web scraping, data processing, and database interactions.
- **Database**: PostgreSQL for persistent storage of product, nutritional, and additive data.
- **Parsing Engine**: Custom logic for E-number extraction and ingredient analysis.

**Key Technical Implementations**:
- **Web Scraping**: Handles dynamic content, extracts product details (name, SKU, ingredients, nutrition), and includes retry logic.
- **Additive Processing**: Identifies and standardizes E-numbers from ingredient lists using regex.
- **Database Management**: Utilizes connection pooling and supports schema creation for products, nutritional data, and additives.
- **Streamlit Interface**: Provides a UI for product search, scraping, data visualization, and real-time feedback with caching.
- **Nutri-Score 2024 Algorithm**: Implements the official 2024 Nutri-Score calculation for 5 product categories, including updated thresholds and specific rules for red meat, cheese, fats/oils/nuts, and beverages.
- **Core Features**: Includes photo extraction, robust nutrition data parsing (with Nutri-Score auto-calculation), comprehensive quantity extraction (including NxM multiplier patterns like "25x2g" → 50g total), enhanced ingredient processing (normalization, deduplication), accurate price parsing, hierarchical category matching, and robust database connection management.
- **Standalone Worker System**: Enables background processing via `worker.py` CLI with priority scheduling, heartbeat monitoring, and fault tolerance. It supports incremental update mode with efficient price scraping directly from category listings, falling back to individual product pages for new items.
- **Combined AI Ingredient Analysis System**: A single AI pass system for categorizing ingredients into 'natural', 'processed', or 'uncategorized' and performing NOVA4 suspicion analysis (e.g., 'avoid', 'limit', 'caution', 'clean'). This combined approach improves performance and uses a specific database schema (`ingredient_analysis`) to store detailed ingredient properties, suspicion levels, and health notes.
- **Data Sharing**: A `product_ingredient_cards` materialized view is available for external projects to display ingredient data, providing SKU, name, ingredient details (cleaned name, category, suspicion level, health note), and summary counts.

## External Dependencies
- **Streamlit**: Web application framework.
- **BeautifulSoup4**: HTML parsing.
- **psycopg2**: PostgreSQL adapter.
- **requests**: HTTP library.
- **pandas**: Data manipulation.
- **trafilatura**: Text extraction from web pages.
- **urllib3**: HTTP client with retry support.
- **google-genai**: Google AI (Gemini) integration for ingredient categorization.