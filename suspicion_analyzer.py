import os
import re
import json
import psycopg2
from psycopg2.extras import RealDictCursor
from google import genai

GEMINI_MODEL = "gemini-2.5-flash"
VALID_LEVELS = {'avoid', 'limit', 'caution', None}
VALID_CATEGORIES = {
    'sweetener', 'emulsifier', 'dye', 'flavor_enhancer', 
    'preservative', 'filler', 'processing_aid', 'industrial_fat', None
}

SUSPICIOUS_ADDITIVES_REFERENCE = """
NOVA 4 SUSPICIOUS ADDITIVES REFERENCE LIST (Latvia/EU):

I. INDUSTRIAL SUGARS & SWEETENERS (category: sweetener) - Level: LIMIT
- Glikozes-fruktozes sīrups (Glucose-fructose syrup/HFCS)
- Invertsukurs (Invert sugar)
- Maltodekstrīns (Maltodextrin)
- Dekstroze (Dextrose)
- E951 Aspartāms (Aspartame)
- E950 Acesulfāms K (Acesulfame K)
- E955 Sukraloze (Sucralose)
- E954 Saharīns (Saccharin)
- E962 Aspartāma-acesulfāma sāls
- E965 Maltīts (Maltitol)
- E420 Sorbīts (Sorbitol)
- E967 Ksilīts (Xylitol)
- E953 Izomalts (Isomalt)
- E968 Eritritols (Erythritol)
- Modificētā ciete (Modified starch E1404-E1452)
- Polidekstroze, Fruktooligosaharīdi, Agaves sīrups

II. INDUSTRIAL FATS & EMULSIFIERS (category: emulsifier/industrial_fat) - Level: LIMIT to AVOID
- Hidrogenēti augu tauki (Hydrogenated fats) - AVOID
- Daļēji hidrogenēti tauki (Partially hydrogenated) - AVOID
- E471 Taukskābju mono- un diglicerīdi - LIMIT
- E322 Sojas lecitīns - CAUTION
- E433 Polisorbiāts 80 - LIMIT (gut inflammation)
- E432-E436 Polisorbiāti - LIMIT
- E466 Karboksimetilceluloze - LIMIT
- E407 Karagināns (Carrageenan) - LIMIT
- E412 Guāra sveķi - CAUTION
- E415 Ksantāna sveķi - CAUTION
- E440 Pektīns (industrial) - CAUTION
- E410 Baltās akācijas sveķi - CAUTION
- E452 Polifosfāti - LIMIT
- E481 Nātrija stearoil-2-laktilāts - LIMIT
- E472e DATEM - LIMIT
- E460 Celuloze - CAUTION
- Palmu tauki (fractionated) - LIMIT

III. DYES - "SOUTHAMPTON SIX" (category: dye) - Level: AVOID
These require EU warning: "May have adverse effect on activity and attention in children"
- E102 Tartrazīns (Yellow 5) - AVOID
- E104 Hinolīna dzeltenais - AVOID
- E110 Saulrieta dzeltenais FCF (Yellow 6) - AVOID
- E122 Azorubīns - AVOID
- E124 Košenila sarkanais 4R - AVOID
- E129 Alura sarkanais AC (Red 40) - AVOID
- E131 Patentzilais V - LIMIT
- E133 Spilgti zilais FCF - LIMIT
- E150c/E150d Amonija karamele - LIMIT
- E120 Karmīns - CAUTION
- E160b Annato - CAUTION
- E172 Dzelzs oksīdi - CAUTION

IV. FLAVOR ENHANCERS (category: flavor_enhancer) - Level: LIMIT to AVOID
"Hyper-palatability" triggers that encourage overeating
- E621 Mononātrija glutamāts (MSG) - LIMIT
- E627 Disonija guanilāts - LIMIT
- E631 Disonija inozināts - LIMIT
- Rauga ekstrakts (hidden MSG) - LIMIT
- Hidrolizētas olbaltumvielas - LIMIT
- Aromatizētāji (generic flavorings) - CAUTION
- Dabīgie aromatizētāji - CAUTION
- Dūmu aromatizētājs - LIMIT
- Etilvanilīns (synthetic vanilla) - CAUTION
- E635 Ribonukleotīdi - LIMIT
- Buljona koncentrāts - CAUTION
- Maltols, Etilmaltols - CAUTION

V. PRESERVATIVES (category: preservative) - Level: LIMIT to AVOID
- E211 Nātrija benzoāts - LIMIT
- E202 Kālija sorbāts - CAUTION
- E250 Nātrija nitrīts - AVOID (carcinogen concern in processed meats)
- E251 Nātrija nitrāts - AVOID
- E252 Kālija nitrāts - AVOID
- E282 Kalcija propionāts - LIMIT
- E220-E228 Sulfīti - LIMIT
- E310 Propilgallāts - AVOID
- E320 BHA - AVOID
- E321 BHT - AVOID
- E385 EDTA - LIMIT
- E210 Benzoskābe - LIMIT
- E218 Parabēni - AVOID

VI. INDUSTRIAL PROTEIN & FILLERS (category: filler) - Level: CAUTION to LIMIT
- Sojas olbaltumvielu izolāts - CAUTION
- Zirņu olbaltumvielas - CAUTION
- Kazeīns (isolated) - CAUTION
- Sūkalu koncentrāts - CAUTION
- Mehāniski atdalīta gaļa - AVOID
- Kviešu lipeklis (added) - CAUTION
- Laktoze (as filler) - CAUTION
- Olu pulveris - CAUTION
- Vājpiena pulveris - CAUTION

VII. PROCESSING AIDS (category: processing_aid) - Level: CAUTION
- E903 Karnaubvasks - CAUTION
- E904 Šellaka - CAUTION
- E500 Nātrija karbonāti - CAUTION
- E450 Difosfāti - LIMIT
- E551 Silīcija dioksīds - CAUTION

SEVERITY LEVELS:
- AVOID: Strong evidence of harm, especially for children, pregnant women, or with regular consumption
- LIMIT: Regular consumption may have negative effects, occasional use acceptable
- CAUTION: Industrial marker, minimal direct harm but indicates ultra-processing
- NULL: Not on suspicious list (natural or non-concerning processed ingredient)

HEALTH NOTES:
- Dyes (Southampton Six): "hyperactivity in children"
- Nitrites/Nitrates: "carcinogen concern"
- Hydrogenated fats: "trans fats, heart disease"
- MSG/flavor enhancers: "overeating trigger"
- Emulsifiers (E433, E407): "gut microbiome disruption"
- Artificial sweeteners: "metabolic effects"
- BHA/BHT: "possible carcinogen"
- Parabens: "endocrine disruption"
"""


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


def validate_suspicion_result(result: dict, ingredient_id: int) -> dict:
    """Validate and normalize AI suspicion result"""
    level = result.get('suspicion_level')
    if level:
        level = str(level).lower().strip()
        if level not in {'avoid', 'limit', 'caution'}:
            level = 'clean'
    else:
        level = 'clean'
    
    category = result.get('suspicion_category')
    if category:
        category = str(category).lower().strip()
        valid_cats = {'sweetener', 'emulsifier', 'dye', 'flavor_enhancer', 
                      'preservative', 'filler', 'processing_aid', 'industrial_fat'}
        if category not in valid_cats:
            category = None
    
    health_note = result.get('health_note')
    if health_note:
        health_note = str(health_note).strip()[:200]
    
    return {
        'id': ingredient_id,
        'suspicion_level': level,
        'suspicion_category': category,
        'health_note': health_note
    }


def analyze_suspicion_batch(ingredients: list[dict], batch_size: int = 50) -> list[dict]:
    """
    Analyze a batch of processed ingredients for NOVA4 suspicion markers.
    
    Args:
        ingredients: List of dicts with 'id', 'ingredient', 'clean_name' keys
        batch_size: Number of ingredients per API call
        
    Returns:
        List of dicts with 'id', 'suspicion_level', 'suspicion_category', 'health_note'
    """
    if not ingredients:
        return []
    
    try:
        client = get_gemini_client()
    except Exception as e:
        print(f"Gemini unavailable: {e}")
        return [{"id": ing["id"], "suspicion_level": "clean", 
                 "suspicion_category": None, "health_note": None} for ing in ingredients]
    
    results = []
    
    for i in range(0, len(ingredients), batch_size):
        batch = ingredients[i:i + batch_size]
        ingredient_list = "\n".join([
            f"{ing['id']}|{ing.get('clean_name') or ing['ingredient']}" 
            for ing in batch
        ])
        
        prompt = f"""You are a food safety expert. Analyze each ingredient for NOVA4 ultra-processed food markers.

CRITICAL E-NUMBER MATCHING (BE AGGRESSIVE):
- E102, E104, E110, E122, E124, E129 = AVOID (Southampton Six dyes, hyperactivity)
- E131, E133, E150c, E150d, E120, E160b, E172, E153, E160a, E161b = dyes, LIMIT/CAUTION
- E250, E251, E252 = AVOID (nitrites/nitrates, carcinogen)
- E310, E320 (BHA), E321 (BHT), E218 = AVOID (carcinogen/endocrine)
- E621, E627, E631, E635 = LIMIT (MSG/flavor enhancers, overeating trigger)
- E211, E202, E282, E210, E385 = LIMIT (preservatives)
- E220-E228 = LIMIT (sulfites)
- E407, E433, E432-E436, E466, E452, E481, E472e, E491, E460 = LIMIT (emulsifiers, gut inflammation)
- E412, E415, E440, E410, E414, E322 = CAUTION (thickeners/emulsifiers)
- E471 = LIMIT (most common UPF emulsifier)
- E951, E950, E955, E954, E962, E965, E420, E967, E953, E968 = LIMIT (artificial sweeteners)
- E1404-E1452 = LIMIT (modified starches)
- E450, E500, E551, E903, E904 = CAUTION (processing aids)
- E492 (sorbitan tristearate) = LIMIT (emulsifier like E491)

OTHER SUSPICIOUS INGREDIENTS:
- Hidrogenēti tauki, daļēji hidrogenēti = AVOID (trans fats)
- Maltodekstrīns, dekstroze, glikozes sīrups = LIMIT (industrial sugars)
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
5. Only return null if ingredient is clearly NOT on any list (e.g., "ūdens", "sāls", "milti")

INPUT: id|ingredient_name
OUTPUT: JSON array with objects:
- id: integer
- suspicion_level: "avoid", "limit", "caution", or null
- suspicion_category: "sweetener", "emulsifier", "dye", "flavor_enhancer", "preservative", "filler", "processing_aid", "industrial_fat", or null
- health_note: brief concern in Latvian (max 50 chars), or null

INGREDIENTS:
{ingredient_list}

Respond with ONLY valid JSON array, no markdown."""

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
                    validated = validate_suspicion_result(batch_by_id[ing_id], ing_id)
                    results.append(validated)
                else:
                    results.append({
                        "id": ing_id,
                        "suspicion_level": "clean",
                        "suspicion_category": None,
                        "health_note": None
                    })
            
        except json.JSONDecodeError as e:
            print(f"JSON parse error: {e}")
            for ing in batch:
                results.append({
                    "id": ing["id"],
                    "suspicion_level": "clean",
                    "suspicion_category": None,
                    "health_note": None
                })
        except Exception as e:
            print(f"Gemini API error: {e}")
            for ing in batch:
                results.append({
                    "id": ing["id"],
                    "suspicion_level": "clean",
                    "suspicion_category": None,
                    "health_note": None
                })
    
    return results


def update_suspicion_in_db(conn, ingredient_id: int, level: str | None, 
                           category: str | None, health_note: str | None):
    """Update suspicion fields for a single ingredient"""
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE ingredient_analysis 
            SET suspicion_level = %s, suspicion_category = %s, health_note = %s
            WHERE id = %s
        """, (level, category, health_note, ingredient_id))
    conn.commit()


def run_suspicion_analysis(batch_size: int = 50, limit: int = None, progress_callback=None):
    """
    Analyze all processed ingredients for NOVA4 suspicion markers.
    
    Args:
        batch_size: Number of ingredients per AI call
        limit: Max ingredients to process (None = all processed)
        progress_callback: Optional callback(processed, total, current_batch) for UI updates
        
    Returns:
        Dict with stats: {'processed': int, 'avoid': int, 'limit': int, 'caution': int, 'clean': int}
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
                WHERE is_processed = true AND suspicion_level IS NULL
            """
            cur.execute(count_query)
            total = cur.fetchone()["total"]
        
        if limit:
            total = min(total, limit)
        
        if total == 0:
            return {"processed": 0, "avoid": 0, "limit": 0, "caution": 0, "clean": 0}
        
        stats = {"processed": 0, "avoid": 0, "limit_count": 0, "caution": 0, "clean": 0}
        processed_total = 0
        
        while processed_total < total:
            with conn.cursor() as cur:
                fetch_query = """
                    SELECT id, ingredient, clean_name 
                    FROM ingredient_analysis 
                    WHERE is_processed = true AND suspicion_level IS NULL
                    ORDER BY frequency DESC, id
                    LIMIT %s
                """
                cur.execute(fetch_query, (batch_size,))
                batch = cur.fetchall()
            
            if not batch:
                break
            
            ingredients = [{"id": row["id"], "ingredient": row["ingredient"], 
                           "clean_name": row["clean_name"]} for row in batch]
            analyzed = analyze_suspicion_batch(ingredients, batch_size=batch_size)
            
            for result in analyzed:
                try:
                    update_suspicion_in_db(
                        conn, 
                        result["id"], 
                        result["suspicion_level"], 
                        result["suspicion_category"], 
                        result["health_note"]
                    )
                    stats["processed"] += 1
                    
                    level = result["suspicion_level"]
                    if level == "avoid":
                        stats["avoid"] += 1
                    elif level == "limit":
                        stats["limit_count"] += 1
                    elif level == "caution":
                        stats["caution"] += 1
                    else:
                        stats["clean"] += 1
                        
                except Exception as e:
                    print(f"DB update error for id {result['id']}: {e}")
            
            processed_total += len(batch)
            
            if progress_callback:
                progress_callback(min(processed_total, total), total, analyzed)
        
        return stats
        
    finally:
        conn.close()


def get_suspicion_stats():
    """Get current suspicion analysis statistics from database"""
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        return None
    
    conn = psycopg2.connect(database_url, cursor_factory=RealDictCursor)
    
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT 
                    COUNT(*) FILTER (WHERE is_processed = true) as total_processed,
                    COUNT(*) FILTER (WHERE suspicion_level = 'avoid') as avoid_count,
                    COUNT(*) FILTER (WHERE suspicion_level = 'limit') as limit_count,
                    COUNT(*) FILTER (WHERE suspicion_level = 'caution') as caution_count,
                    COUNT(*) FILTER (WHERE suspicion_level = 'clean') as clean_count,
                    COUNT(*) FILTER (WHERE is_processed = true AND suspicion_level IS NULL) as unanalyzed,
                    COUNT(*) FILTER (WHERE is_processed = true AND suspicion_level IS NOT NULL) as analyzed
                FROM ingredient_analysis
            """)
            return cur.fetchone()
    finally:
        conn.close()


def reset_suspicion_analysis():
    """Reset all suspicion fields to NULL for re-analysis"""
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise ValueError("DATABASE_URL not set")
    
    conn = psycopg2.connect(database_url)
    try:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE ingredient_analysis 
                SET suspicion_level = NULL, suspicion_category = NULL, health_note = NULL
                WHERE is_processed = true
            """)
        conn.commit()
    finally:
        conn.close()
