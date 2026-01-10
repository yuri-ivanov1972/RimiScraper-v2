import os
import re
import json
import psycopg2
from psycopg2.extras import RealDictCursor
from google import genai

GEMINI_MODEL = "gemini-2.5-flash"
VALID_CATEGORIES = {'natural', 'processed', 'uncategorized'}

def get_gemini_client():
    """Get Gemini client using Replit AI Integrations"""
    api_key = os.environ.get("AI_INTEGRATIONS_GEMINI_API_KEY")
    base_url = os.environ.get("AI_INTEGRATIONS_GEMINI_BASE_URL")
    
    if not api_key:
        raise ValueError("AI_INTEGRATIONS_GEMINI_API_KEY not set")
    
    client = genai.Client(
        api_key=api_key,
        http_options={
            'api_version': '',
            'base_url': base_url
        }
    )
    return client


def validate_and_normalize_result(result: dict, original_ingredient: str) -> dict:
    """Validate and normalize AI result to ensure correct data types"""
    clean_name = result.get('clean_name') or clean_ingredient_name(original_ingredient)
    
    category = str(result.get('category', 'uncategorized')).lower().strip()
    if category not in VALID_CATEGORIES:
        category = 'uncategorized'
    
    if category == 'natural':
        is_processed = False
    elif category == 'processed':
        is_processed = True
    else:
        is_processed = None
    
    return {
        'clean_name': clean_name,
        'category': category,
        'is_processed': is_processed
    }


def clean_ingredient_name(ingredient: str) -> str:
    """Clean ingredient name by removing unnecessary characters"""
    if not ingredient:
        return ""
    
    cleaned = ingredient.strip()
    cleaned = re.sub(r'\([^)]*\)', '', cleaned)
    cleaned = re.sub(r'[\*\(\)\[\]\{\}]', '', cleaned)
    cleaned = re.sub(r'\d+[,.]?\d*\s*%', '', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned)
    cleaned = cleaned.strip(' ,;:.')
    
    return cleaned.strip()


def categorize_ingredients_batch(ingredients: list[dict], batch_size: int = 50) -> list[dict]:
    """
    Categorize a batch of ingredients using Gemini AI.
    Option A: Batch processing for backfill (faster, fewer API calls)
    
    Args:
        ingredients: List of dicts with 'id' and 'ingredient' keys
        batch_size: Number of ingredients per API call
        
    Returns:
        List of dicts with 'id', 'clean_name', 'category', 'is_processed'
    """
    if not ingredients:
        return []
    
    try:
        client = get_gemini_client()
    except Exception as e:
        print(f"Gemini unavailable: {e}")
        return [{"id": ing["id"], "clean_name": clean_ingredient_name(ing["ingredient"]), 
                 "category": "uncategorized", "is_processed": None} for ing in ingredients]
    
    results = []
    
    for i in range(0, len(ingredients), batch_size):
        batch = ingredients[i:i + batch_size]
        ingredient_list = "\n".join([f"{ing['id']}|{ing['ingredient']}" for ing in batch])
        
        prompt = f"""You are a food ingredient categorization expert. Analyze each ingredient and categorize it.

CATEGORIES:
- natural: Whole foods, unprocessed ingredients (fruits, vegetables, meat, fish, eggs, milk, water, herbs, spices, nuts, seeds, grains, legumes, honey)
- processed: Refined, modified, or industrial ingredients (E-numbers, preservatives, emulsifiers, stabilizers, artificial colors/flavors, refined sugars, modified starches, hydrogenated fats, flavor enhancers)

SYNONYM HANDLING:
- If an ingredient is essentially the same as another (e.g., "ūdens" and "dzeramais ūdens" are both water), use the simplest/most common clean_name
- Common synonyms should get the same clean_name to enable grouping

CLEANING RULES:
- Remove parentheses and their contents
- Remove percentages and numbers
- Remove asterisks and special characters
- Keep the essential ingredient name in Latvian

INPUT FORMAT: id|ingredient
OUTPUT FORMAT: JSON array with objects containing: id, clean_name, category, is_processed

INGREDIENTS TO CATEGORIZE:
{ingredient_list}

Respond ONLY with a valid JSON array, no other text."""

        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt
            )
            
            response_text = response.text.strip()
            if response_text.startswith("```"):
                response_text = re.sub(r'^```json?\n?', '', response_text)
                response_text = re.sub(r'\n?```$', '', response_text)
            
            batch_results = json.loads(response_text)
            
            batch_by_id = {r.get('id'): r for r in batch_results if r.get('id')}
            
            for ing in batch:
                ing_id = ing['id']
                if ing_id in batch_by_id:
                    validated = validate_and_normalize_result(batch_by_id[ing_id], ing['ingredient'])
                    validated['id'] = ing_id
                    results.append(validated)
                else:
                    results.append({
                        "id": ing_id,
                        "clean_name": clean_ingredient_name(ing["ingredient"]),
                        "category": "uncategorized",
                        "is_processed": None
                    })
            
        except json.JSONDecodeError as e:
            print(f"JSON parse error: {e}")
            for ing in batch:
                results.append({
                    "id": ing["id"],
                    "clean_name": clean_ingredient_name(ing["ingredient"]),
                    "category": "uncategorized",
                    "is_processed": None
                })
        except Exception as e:
            print(f"Gemini API error: {e}")
            for ing in batch:
                results.append({
                    "id": ing["id"],
                    "clean_name": clean_ingredient_name(ing["ingredient"]),
                    "category": "uncategorized",
                    "is_processed": None
                })
    
    return results


def categorize_single_ingredient(ingredient: str) -> dict:
    """
    Categorize a single ingredient using Gemini AI.
    Option B: For new ingredients during scraping
    
    Args:
        ingredient: Raw ingredient name
        
    Returns:
        Dict with 'clean_name', 'category', 'is_processed'
    """
    clean_name = clean_ingredient_name(ingredient)
    
    try:
        client = get_gemini_client()
    except Exception as e:
        print(f"Gemini unavailable: {e}")
        return {"clean_name": clean_name, "category": "uncategorized", "is_processed": None}
    
    prompt = f"""Categorize this food ingredient:
Ingredient: {ingredient}

Categories:
- natural: Whole foods, unprocessed (fruits, vegetables, meat, fish, eggs, milk, water, herbs, spices, nuts, seeds, grains, legumes, honey)
- processed: Refined/industrial (E-numbers, preservatives, emulsifiers, stabilizers, artificial colors/flavors, refined sugars, modified starches)

Respond with ONLY a JSON object: {{"clean_name": "cleaned ingredient name in Latvian", "category": "natural or processed", "is_processed": true/false}}"""

    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt
        )
        
        response_text = response.text.strip()
        if response_text.startswith("```"):
            response_text = re.sub(r'^```json?\n?', '', response_text)
            response_text = re.sub(r'\n?```$', '', response_text)
        
        result = json.loads(response_text)
        return validate_and_normalize_result(result, ingredient)
        
    except Exception as e:
        print(f"Gemini error: {e}")
        return {"clean_name": clean_name, "category": "uncategorized", "is_processed": None}


def update_ingredient_in_db(conn, ingredient_id: int, clean_name: str, category: str, is_processed: bool | None):
    """Update a single ingredient record in the database"""
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE ingredient_analysis 
            SET clean_name = %s, category = %s, is_processed = %s
            WHERE id = %s
        """, (clean_name, category, is_processed, ingredient_id))
    conn.commit()


def backfill_uncategorized_ingredients(batch_size: int = 50, limit: int = None, progress_callback=None):
    """
    Backfill all uncategorized ingredients using batch AI categorization.
    
    Args:
        batch_size: Number of ingredients per AI call
        limit: Max ingredients to process (None = all)
        progress_callback: Optional callback(processed, total, current_batch) for UI updates
        
    Returns:
        Dict with stats: {'processed': int, 'natural': int, 'processed': int, 'failed': int}
    """
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise ValueError("DATABASE_URL not set")
    
    conn = psycopg2.connect(database_url, cursor_factory=RealDictCursor)
    
    try:
        with conn.cursor() as cur:
            count_query = """
                SELECT COUNT(*) as total 
                FROM ingredient_analysis 
                WHERE category = 'uncategorized' OR category IS NULL
            """
            cur.execute(count_query)
            total = cur.fetchone()["total"]
        
        if limit:
            total = min(total, limit)
        
        stats = {"processed": 0, "natural": 0, "processed_count": 0, "failed": 0}
        processed_total = 0
        
        while processed_total < total:
            with conn.cursor() as cur:
                fetch_query = """
                    SELECT id, ingredient 
                    FROM ingredient_analysis 
                    WHERE category = 'uncategorized' OR category IS NULL
                    ORDER BY frequency DESC, id
                    LIMIT %s
                """
                cur.execute(fetch_query, (batch_size,))
                batch = cur.fetchall()
            
            if not batch:
                break
            
            ingredients = [{"id": row["id"], "ingredient": row["ingredient"]} for row in batch]
            categorized = categorize_ingredients_batch(ingredients, batch_size=batch_size)
            
            for result in categorized:
                try:
                    update_ingredient_in_db(
                        conn, 
                        result["id"], 
                        result["clean_name"], 
                        result["category"], 
                        result["is_processed"]
                    )
                    stats["processed"] += 1
                    if result["category"] == "natural":
                        stats["natural"] += 1
                    elif result["category"] == "processed":
                        stats["processed_count"] += 1
                except Exception as e:
                    print(f"DB update error for id {result['id']}: {e}")
                    stats["failed"] += 1
            
            processed_total += len(batch)
            
            if progress_callback:
                progress_callback(min(processed_total, total), total, categorized)
        
        return stats
        
    finally:
        conn.close()


def get_categorization_stats():
    """Get current categorization statistics from database"""
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        return None
    
    conn = psycopg2.connect(database_url, cursor_factory=RealDictCursor)
    
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT 
                    COUNT(*) as total,
                    COUNT(*) FILTER (WHERE category = 'natural') as natural,
                    COUNT(*) FILTER (WHERE category = 'processed') as processed,
                    COUNT(*) FILTER (WHERE category = 'uncategorized' OR category IS NULL) as uncategorized
                FROM ingredient_analysis
            """)
            return cur.fetchone()
    finally:
        conn.close()
