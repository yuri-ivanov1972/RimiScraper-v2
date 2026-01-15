import os
import re
import json
import psycopg2
from psycopg2.extras import RealDictCursor
from google import genai

GEMINI_MODEL = "gemini-2.5-flash"
BATCH_SIZE = 40

VALID_CATEGORIES = {'natural', 'processed', 'uncategorized'}
VALID_SUSPICION_LEVELS = {'avoid', 'limit', 'caution', 'clean'}
VALID_SUSPICION_CATEGORIES = {
    'sweetener', 'emulsifier', 'dye', 'flavor_enhancer', 
    'preservative', 'filler', 'processing_aid', 'industrial_fat'
}


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


def validate_combined_result(result: dict, original_ingredient: str, ingredient_id: int) -> dict:
    """Validate and normalize the combined AI result"""
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
    
    suspicion_level = result.get('suspicion_level')
    if suspicion_level:
        suspicion_level = str(suspicion_level).lower().strip()
        if suspicion_level not in {'avoid', 'limit', 'caution'}:
            suspicion_level = 'clean' if is_processed else None
    else:
        suspicion_level = 'clean' if is_processed else None
    
    suspicion_category = result.get('suspicion_category')
    if suspicion_category:
        suspicion_category = str(suspicion_category).lower().strip()
        if suspicion_category not in VALID_SUSPICION_CATEGORIES:
            suspicion_category = None
    
    health_note = result.get('health_note')
    if health_note:
        health_note = str(health_note).strip()[:200]
    
    return {
        'id': ingredient_id,
        'clean_name': clean_name,
        'category': category,
        'is_processed': is_processed,
        'suspicion_level': suspicion_level,
        'suspicion_category': suspicion_category,
        'health_note': health_note
    }


def get_fallback_result(ingredient: str, ingredient_id: int) -> dict:
    """Return fallback result when AI is unavailable"""
    return {
        'id': ingredient_id,
        'clean_name': clean_ingredient_name(ingredient),
        'category': 'uncategorized',
        'is_processed': None,
        'suspicion_level': None,
        'suspicion_category': None,
        'health_note': None
    }


COMBINED_PROMPT_TEMPLATE = """You are a food safety expert. Analyze each ingredient for BOTH:
1. Category (natural vs processed)
2. NOVA4 suspicion markers (if processed)

CATEGORIZATION RULES:
- NATURAL: Whole foods (fruits, vegetables, meat, fish, eggs, milk, water, herbs, spices, nuts, seeds, grains, legumes, honey)
- PROCESSED: Refined/industrial ingredients (E-numbers, preservatives, emulsifiers, stabilizers, artificial colors/flavors, refined sugars, modified starches, hydrogenated fats)

CRITICAL E-NUMBER MATCHING (BE AGGRESSIVE):
- E102, E104, E110, E122, E124, E129 = AVOID (Southampton Six dyes)
- E131, E133, E150c, E150d, E120, E160b, E172, E153, E160a, E161b = dyes, LIMIT/CAUTION
- E250, E251, E252 = AVOID (nitrites/nitrates, carcinogen)
- E310, E320 (BHA), E321 (BHT), E218 = AVOID (carcinogen/endocrine)
- E621, E627, E631, E635 = LIMIT (MSG/flavor enhancers)
- E211, E202, E282, E210, E385 = LIMIT (preservatives)
- E220-E228 = LIMIT (sulfites)
- E407, E433, E432-E436, E466, E452, E481, E472e, E491, E492, E460 = LIMIT (emulsifiers)
- E412, E415, E440, E410, E414, E322 = CAUTION (thickeners/emulsifiers)
- E471 = LIMIT (most common UPF emulsifier)
- E951, E950, E955, E954, E962, E965, E420, E967, E953, E968 = LIMIT (artificial sweeteners)
- E1404-E1452 = LIMIT (modified starches)
- E450, E500, E551, E903, E904 = CAUTION (processing aids)

OTHER SUSPICIOUS INGREDIENTS:
- Hidrogenēti tauki, daļēji hidrogenēti = AVOID (trans fats)
- Maltodekstrīns, dekstroze, glikozes sīrups, invertsukurs = LIMIT (industrial sugars)
- Aromatizētāji, dabīgie aromatizētāji = CAUTION (flavor enhancers)
- Rauga ekstrakts = LIMIT (hidden MSG)
- Mehāniski atdalīta gaļa = AVOID
- Sojas/zirņu olbaltumvielu izolāts, kazeīns, vājpiena pulveris = CAUTION (fillers)
- Palmu tauki (fractionated) = LIMIT

MATCHING RULES:
1. EXTRACT E-numbers from text (e.g., "emulgatori e492" → match E492)
2. E-numbers are case-insensitive (e492 = E492)
3. Match Latvian names: "guāra sveķi" = E412, "ksantāna sveķi" = E415, "karagināns" = E407
4. Be GENEROUS in matching - if it looks like a suspicious additive, flag it
5. Natural ingredients get suspicion_level: null (NOT "clean")

CLEAN NAME RULES:
- Remove parentheses, percentages, asterisks
- Keep essential Latvian ingredient name
- Use common form for synonyms (e.g., "ūdens" for all water variants)

SEVERITY LEVELS:
- AVOID: Strong harm evidence (carcinogens, trans fats, Southampton Six dyes)
- LIMIT: Regular consumption may harm (emulsifiers, MSG, artificial sweeteners)
- CAUTION: Ultra-processing marker, minimal direct harm
- null: Natural ingredient OR processed but not suspicious

INPUT: id|ingredient_name
OUTPUT: JSON array with objects:
- id: integer
- clean_name: string (cleaned Latvian name)
- category: "natural" or "processed"
- is_processed: boolean
- suspicion_level: "avoid", "limit", "caution", or null
- suspicion_category: "sweetener", "emulsifier", "dye", "flavor_enhancer", "preservative", "filler", "processing_aid", "industrial_fat", or null
- health_note: brief concern in Latvian (max 50 chars), or null

INGREDIENTS:
{ingredient_list}

Respond with ONLY valid JSON array, no markdown."""


def analyze_ingredients_batch(ingredients: list[dict], batch_size: int = BATCH_SIZE) -> list[dict]:
    """
    Combined analysis: categorization + suspicion in single AI call.
    
    Args:
        ingredients: List of dicts with 'id' and 'ingredient' keys
        batch_size: Number of ingredients per API call (default 40 for accuracy)
        
    Returns:
        List of dicts with all 7 fields: id, clean_name, category, is_processed,
        suspicion_level, suspicion_category, health_note
    """
    if not ingredients:
        return []
    
    try:
        client = get_gemini_client()
    except Exception as e:
        print(f"Gemini unavailable: {e}")
        return [get_fallback_result(ing["ingredient"], ing["id"]) for ing in ingredients]
    
    results = []
    
    for i in range(0, len(ingredients), batch_size):
        batch = ingredients[i:i + batch_size]
        ingredient_list = "\n".join([f"{ing['id']}|{ing['ingredient']}" for ing in batch])
        
        prompt = COMBINED_PROMPT_TEMPLATE.format(ingredient_list=ingredient_list)
        
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
                    validated = validate_combined_result(
                        batch_by_id[ing_id], 
                        ing['ingredient'], 
                        ing_id
                    )
                    results.append(validated)
                else:
                    results.append(get_fallback_result(ing["ingredient"], ing_id))
            
        except json.JSONDecodeError as e:
            print(f"JSON parse error: {e}")
            for ing in batch:
                results.append(get_fallback_result(ing["ingredient"], ing["id"]))
        except Exception as e:
            print(f"Gemini API error: {e}")
            for ing in batch:
                results.append(get_fallback_result(ing["ingredient"], ing["id"]))
    
    return results


def update_ingredient_combined(conn, result: dict):
    """Update all fields for a single ingredient in one transaction"""
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE ingredient_analysis 
            SET clean_name = %s,
                category = %s,
                is_processed = %s,
                suspicion_level = %s,
                suspicion_category = %s,
                health_note = %s
            WHERE id = %s
        """, (
            result['clean_name'],
            result['category'],
            result['is_processed'],
            result['suspicion_level'],
            result['suspicion_category'],
            result['health_note'],
            result['id']
        ))
    conn.commit()


def batch_update_ingredients(conn, results: list[dict]):
    """Update multiple ingredients in a single transaction"""
    if not results:
        return 0
    
    with conn.cursor() as cur:
        for result in results:
            cur.execute("""
                UPDATE ingredient_analysis 
                SET clean_name = %s,
                    category = %s,
                    is_processed = %s,
                    suspicion_level = %s,
                    suspicion_category = %s,
                    health_note = %s
                WHERE id = %s
            """, (
                result['clean_name'],
                result['category'],
                result['is_processed'],
                result['suspicion_level'],
                result['suspicion_category'],
                result['health_note'],
                result['id']
            ))
    conn.commit()
    return len(results)


def get_unanalyzed_ingredients(limit: int = 1000) -> list[dict]:
    """Get ingredients that haven't been analyzed yet (category is NULL or uncategorized)"""
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        return []
    
    conn = psycopg2.connect(database_url, cursor_factory=RealDictCursor)
    
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, ingredient 
                FROM ingredient_analysis 
                WHERE category IS NULL OR category = 'uncategorized'
                ORDER BY frequency DESC NULLS LAST
                LIMIT %s
            """, (limit,))
            return list(cur.fetchall())
    finally:
        conn.close()


def get_incomplete_suspicion_ingredients(limit: int = 1000) -> list[dict]:
    """Get processed ingredients that are missing suspicion analysis (category set but suspicion_level is NULL)"""
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        return []
    
    conn = psycopg2.connect(database_url, cursor_factory=RealDictCursor)
    
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, ingredient 
                FROM ingredient_analysis 
                WHERE category = 'processed' AND is_processed = true AND suspicion_level IS NULL
                ORDER BY frequency DESC NULLS LAST
                LIMIT %s
            """, (limit,))
            return list(cur.fetchall())
    finally:
        conn.close()


def fix_incomplete_suspicion(progress_callback=None) -> dict:
    """
    Fix processed ingredients that are missing suspicion analysis.
    These were categorized by the old categorizer but never got suspicion analysis.
    
    Args:
        progress_callback: Optional function(processed, total) for progress updates
        
    Returns:
        Dict with statistics
    """
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        return {"error": "DATABASE_URL not set"}
    
    conn = psycopg2.connect(database_url, cursor_factory=RealDictCursor)
    
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*) as count 
                FROM ingredient_analysis 
                WHERE category = 'processed' AND is_processed = true AND suspicion_level IS NULL
            """)
            total = cur.fetchone()['count']
        
        if total == 0:
            return {"message": "No incomplete ingredients found", "processed": 0}
        
        processed = 0
        batch_num = 0
        
        while True:
            ingredients = get_incomplete_suspicion_ingredients(limit=BATCH_SIZE)
            
            if not ingredients:
                break
            
            batch_num += 1
            results = analyze_ingredients_batch(ingredients, batch_size=BATCH_SIZE)
            
            if results:
                batch_update_ingredients(conn, results)
            
            processed += len(results)
            
            if progress_callback:
                progress_callback(processed, total)
            
            print(f"Fixed batch {batch_num}: {len(results)} ingredients ({processed}/{total})")
        
        return {
            "message": "Completed fixing incomplete suspicion analysis",
            "processed": processed,
            "total": total
        }
    finally:
        conn.close()


def get_analysis_stats() -> dict:
    """Get combined analysis statistics"""
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        return None
    
    conn = psycopg2.connect(database_url, cursor_factory=RealDictCursor)
    
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT 
                    COUNT(*) as total,
                    COUNT(*) FILTER (WHERE category = 'natural') as natural_count,
                    COUNT(*) FILTER (WHERE category = 'processed') as processed_count,
                    COUNT(*) FILTER (WHERE category = 'uncategorized' OR category IS NULL) as unanalyzed,
                    COUNT(*) FILTER (WHERE suspicion_level = 'avoid') as avoid_count,
                    COUNT(*) FILTER (WHERE suspicion_level = 'limit') as limit_count,
                    COUNT(*) FILTER (WHERE suspicion_level = 'caution') as caution_count,
                    COUNT(*) FILTER (WHERE suspicion_level = 'clean') as clean_count,
                    COUNT(*) FILTER (WHERE category = 'natural' AND suspicion_level IS NULL) as natural_null_suspicion,
                    COUNT(*) FILTER (WHERE category = 'processed' AND is_processed = true AND suspicion_level IS NULL) as incomplete_suspicion
                FROM ingredient_analysis
            """)
            return cur.fetchone()
    finally:
        conn.close()


def run_test_batch(batch_count: int = 1) -> list[dict]:
    """
    Run test batches without saving to database.
    Returns results for review before full processing.
    """
    ingredients = get_unanalyzed_ingredients(limit=BATCH_SIZE * batch_count)
    
    if not ingredients:
        return []
    
    results = analyze_ingredients_batch(ingredients, batch_size=BATCH_SIZE)
    return results


def run_full_analysis(progress_callback=None) -> dict:
    """
    Run full combined analysis on all unanalyzed ingredients.
    Uses single connection throughout for transaction consistency.
    
    Args:
        progress_callback: Optional function(processed, total) for progress updates
        
    Returns:
        Dict with statistics
    """
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        return {"error": "DATABASE_URL not set"}
    
    conn = psycopg2.connect(database_url, cursor_factory=RealDictCursor)
    
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*) as total
                FROM ingredient_analysis 
                WHERE category IS NULL OR category = 'uncategorized'
            """)
            total = cur.fetchone()['total']
        
        if total == 0:
            return {"message": "All ingredients already analyzed", "processed": 0}
        
        processed = 0
        batch_num = 0
        
        while True:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, ingredient 
                    FROM ingredient_analysis 
                    WHERE category IS NULL OR category = 'uncategorized'
                    ORDER BY frequency DESC NULLS LAST
                    LIMIT %s
                """, (BATCH_SIZE,))
                ingredients = list(cur.fetchall())
            
            if not ingredients:
                break
            
            results = analyze_ingredients_batch(ingredients, batch_size=BATCH_SIZE)
            batch_update_ingredients(conn, results)
            
            processed += len(results)
            batch_num += 1
            
            if progress_callback:
                progress_callback(processed, total)
            
            print(f"Batch {batch_num}: processed {len(results)} ingredients ({processed}/{total})")
        
        return {
            "processed": processed,
            "total": total,
            "batches": batch_num
        }
    
    finally:
        conn.close()


def reset_all_analysis():
    """Reset all analysis fields for re-processing"""
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        return 0
    
    conn = psycopg2.connect(database_url)
    
    try:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE ingredient_analysis 
                SET category = NULL,
                    is_processed = NULL,
                    suspicion_level = NULL,
                    suspicion_category = NULL,
                    health_note = NULL
            """)
            count = cur.rowcount
        conn.commit()
        return count
    finally:
        conn.close()
