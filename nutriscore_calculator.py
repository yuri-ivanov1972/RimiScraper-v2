"""
Nutri-Score 2.0 (2024) Calculator Module
Updated to implement the official 2024 Nutri-Score algorithm.

Supports 5 product categories:
1. General Foods (cereals, ready meals, etc.)
2. Red Meat (capped protein points)
3. Cheese (exempt from protein block)
4. Fats, Oils, Nuts, and Seeds (energy from saturates, sat/fat ratio)
5. Beverages (stricter thresholds, sweetener penalty)

Usage:
    from nutriscore_calculator import NutriscoreCalculator
    
    calculator = NutriscoreCalculator(database_connection)
    result = calculator.calculate_single_product(
        energy_kj=1500,
        sugars=10.5,
        saturated_fat=3.2,
        salt=1.8,
        protein=12.0,
        fiber=5,
        total_fat=15.0,
        category_id=42
    )
    print(f"Nutriscore: {result['grade']} (Score: {result['score']})")
"""

from typing import Any, Dict, Optional, Tuple
import math


def validate_fvl_percentage(value):
    """None means category default; zero is a real product override."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Fruit/vegetable/legume percentage must be between 0 and 100") from exc
    if not math.isfinite(number) or not 0 <= number <= 100:
        raise ValueError("Fruit/vegetable/legume percentage must be between 0 and 100")
    return round(number, 2)


_CATEGORY_TYPE_TO_SCORING_CATEGORY = {
    "general": "general",
    "beverage": "beverage",
    "cheese": "cheese",
    "red_meat": "red_meat",
    "fat_oil_nut": "fats_oils_nuts",
    "full_fvn": "general",
    "half_fvn": "general",
}
_CATEGORY_TYPE_TO_FVN_PERCENTAGE = {"full_fvn": 100.0, "half_fvn": 50.0}

LATVIAN_SWEETENER_INDICATORS = [
    'saldināšanas līdzeklis', 'saldinātājs', 'saldinātāji',
    'aspartāms', 'aspartam',
    'acesulfāms', 'acesulfāms k', 'acesulfam',
    'sukraloze', 'sukraloz', 'sucralose',
    'saharīns', 'sacharin',
    'ciklamāts', 'ciklamāt', 'cyclamate',
    'neotāms', 'neotam',
    'advantāms', 'advantam',
    'stevijas glikozīdi', 'stevia', 'steviol',
    'taumatīns', 'thaumatin',
    'maltīts', 'maltitol',
    'sorbīts', 'sorbitol',
    'ksilitols', 'xylitol',
    'eritritols', 'erythritol',
    'izomaltīts', 'isomalt',
    'mannīts', 'mannitol',
    'zero', 'light', 'diet', 'bez cukura', 'sugar free', 'sugar-free',
    'bezkaloriju', 'bez kalorijām',
    'e950', 'e951', 'e952', 'e953', 'e954', 'e955', 
    'e957', 'e959', 'e960', 'e961', 'e962', 'e965', 
    'e966', 'e967', 'e968', 'e969',
]


def get_points(value: float, thresholds: list) -> int:
    """Helper to determine points based on a list of upper limits."""
    for points, limit in enumerate(thresholds):
        if value <= limit:
            return points
    return len(thresholds)


def calculate_nutriscore_2024(
    category: str,
    energy_kj: float,
    sugars_g: float,
    sat_fat_g: float,
    salt_g: float,
    protein_g: float,
    fiber_g: float = 0,
    fvl_pct: float = 0,
    total_fat_g: Optional[float] = None,
    has_sweeteners: bool = False
) -> Dict[str, Any]:
    """
    Calculate Nutri-Score 2.0 (2024 official algorithm).
    
    Args:
        category: 'general', 'red_meat', 'cheese', 'fats_oils_nuts', 'beverage'
        energy_kj: Energy in kJ/100g
        sugars_g: Sugars in g/100g
        sat_fat_g: Saturated fat in g/100g
        salt_g: Salt in g/100g
        protein_g: Protein in g/100g
        fiber_g: Fiber in g/100g
        fvl_pct: Fruits/vegetables/legumes percentage (0-100)
        total_fat_g: Total fat in g/100g (required for fats_oils_nuts category)
        has_sweeteners: Whether product contains artificial sweeteners (beverages)
    
    Returns:
        Dictionary with grade, score, n_points, p_points, p_status, components
    """
    
    t_energy_gen = [335, 670, 1005, 1340, 1675, 2010, 2345, 2680, 3015, 3350]
    t_sugar_gen = [3.4, 6.8, 10, 14, 17, 20, 24, 27, 31, 34, 37, 41, 44, 48, 51]
    t_satfat_gen = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    t_salt_gen = [0.2, 0.4, 0.6, 0.8, 1.0, 1.2, 1.4, 1.6, 1.8, 2.0,
                  2.2, 2.4, 2.6, 2.8, 3.0, 3.2, 3.4, 3.6, 3.8, 4.0]
    
    t_energy_bev = [30, 90, 150, 210, 240, 270, 300, 330, 360, 390]
    t_sugar_bev = [0.5, 2, 3.5, 5, 6, 7, 8, 9, 10, 11]
    
    t_fiber_gen = [3.0, 4.1, 5.2, 6.3, 7.4]
    t_protein_gen = [2.4, 4.8, 7.2, 9.6, 12, 14, 17]
    t_fvl_gen = [40, 60, 80]
    
    t_protein_bev = [1.2, 1.5, 1.8, 2.1, 2.4, 2.7, 3.0]
    t_fiber_bev = [3, 4.1, 5.2, 6.3, 7.4]
    t_fvl_bev = [40, 60, 80]
    
    p_sweetener = 0
    protein_status = "included"
    
    if category == 'beverage':
        p_energy = get_points(energy_kj, t_energy_bev)
        p_sugar = get_points(sugars_g, t_sugar_bev)
        p_salt = get_points(salt_g, t_salt_gen)
        p_satfat = get_points(sat_fat_g, t_satfat_gen)
        p_sweetener = 4 if has_sweeteners else 0
        total_n = p_energy + p_sugar + p_salt + p_satfat + p_sweetener
        
        p_protein = get_points(protein_g, t_protein_bev)
        p_fiber = get_points(fiber_g, t_fiber_bev)
        fvl_raw = get_points(fvl_pct, t_fvl_bev)
        p_fvl = [0, 2, 4, 6][fvl_raw] if fvl_raw <= 3 else 6
        total_p = p_protein + p_fiber + p_fvl
        
    elif category == 'fats_oils_nuts':
        energy_from_satfat = sat_fat_g * 37
        p_energy = get_points(energy_from_satfat, [120 * i for i in range(1, 11)])
        
        if total_fat_g and total_fat_g > 0:
            ratio = (sat_fat_g / total_fat_g) * 100
        else:
            ratio = 0
        p_satfat = get_points(ratio, [10, 16, 22, 28, 34, 40, 46, 52, 58, 64])
        
        p_sugar = get_points(sugars_g, t_sugar_gen)
        p_salt = get_points(salt_g, t_salt_gen)
        total_n = p_energy + p_sugar + p_salt + p_satfat
        
        p_protein = get_points(protein_g, t_protein_gen)
        p_fiber = get_points(fiber_g, t_fiber_gen)
        fvl_raw = get_points(fvl_pct, t_fvl_gen)
        p_fvl = 5 if fvl_raw == 3 else fvl_raw
        total_p = p_protein + p_fiber + p_fvl
        
    else:
        p_energy = get_points(energy_kj, t_energy_gen)
        p_sugar = get_points(sugars_g, t_sugar_gen)
        p_satfat = get_points(sat_fat_g, t_satfat_gen)
        p_salt = get_points(salt_g, t_salt_gen)
        total_n = p_energy + p_sugar + p_satfat + p_salt
        
        p_protein = get_points(protein_g, t_protein_gen)
        if category == 'red_meat':
            p_protein = min(p_protein, 2)
            protein_status = f"capped_at_2 (was {get_points(protein_g, t_protein_gen)})"
        
        p_fiber = get_points(fiber_g, t_fiber_gen)
        fvl_raw = get_points(fvl_pct, t_fvl_gen)
        p_fvl = 5 if fvl_raw == 3 else fvl_raw
        total_p = p_protein + p_fiber + p_fvl
    
    final_score = total_n - total_p
    
    if category not in ['cheese', 'beverage']:
        if total_n >= 11 and p_fvl < 5:
            final_score = total_n - (p_fiber + p_fvl)
            protein_status = f"blocked (N={total_n}, FVL={p_fvl})"
            total_p = p_fiber + p_fvl
    
    if category == 'beverage':
        if energy_kj == 0 and sugars_g == 0 and not has_sweeteners:
            grade = "A"
        elif final_score <= 2:
            grade = "B"
        elif final_score <= 6:
            grade = "C"
        elif final_score <= 9:
            grade = "D"
        else:
            grade = "E"
    elif category == 'fats_oils_nuts':
        if final_score <= -6:
            grade = "A"
        elif final_score <= 2:
            grade = "B"
        elif final_score <= 10:
            grade = "C"
        elif final_score <= 18:
            grade = "D"
        else:
            grade = "E"
    else:
        if final_score < 1:
            grade = "A"
        elif final_score <= 2:
            grade = "B"
        elif final_score <= 10:
            grade = "C"
        elif final_score <= 18:
            grade = "D"
        else:
            grade = "E"
    
    components = {
        'energy_points': p_energy,
        'sugar_points': p_sugar,
        'satfat_points': p_satfat,
        'salt_points': p_salt,
        'sweetener_points': p_sweetener,
        'protein_points': p_protein,
        'fiber_points': p_fiber,
        'fvl_points': p_fvl,
        'negative_total': total_n,
        'positive_total': total_p,
    }
    
    return {
        'grade': grade,
        'score': final_score,
        'n_points': total_n,
        'p_points': total_p,
        'protein_status': protein_status,
        'components': components
    }


class NutriscoreCalculator:
    """
    Nutri-Score 2.0 (2024) Calculator.
    Can be used by other Replit applications.
    """
    
    def __init__(self, connection=None):
        """Create a calculator backed by an existing database connection."""
        self.connection = connection
        self._category_type_cache: Dict[int, str] = {}
    
    def _detect_sweeteners(self, product_name: Optional[str], ingredients_text: Optional[str] = None) -> bool:
        """Detect if product likely contains artificial sweeteners based on name/ingredients.
        
        Uses LATVIAN_SWEETENER_INDICATORS which includes:
        - Latvian sweetener names (saldināšanas līdzeklis, aspartāms, sukraloze, etc.)
        - English equivalents for international products
        - E-numbers for artificial sweeteners (E950-E969)
        - Marketing terms (zero, light, diet, bez cukura)
        """
        text_to_check = (product_name or '').lower()
        if ingredients_text:
            text_to_check += ' ' + ingredients_text.lower()
        
        return any(indicator in text_to_check for indicator in LATVIAN_SWEETENER_INDICATORS)
    
    def _get_category_type(self, category_id: Optional[int]) -> str:
        """Read and cache one saved Nutri-Score type from normalized_categories."""
        if category_id is None or category_id == "":
            raise ValueError("A category_id is required for Nutri-Score calculation.")
        if self.connection is None:
            raise RuntimeError(
                "A database connection is required to resolve the saved Nutri-Score category type."
            )

        try:
            cache_key = int(category_id)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid category_id: {category_id!r}") from exc

        if cache_key in self._category_type_cache:
            return self._category_type_cache[cache_key]

        try:
            with self.connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT nutriscore_category_type
                    FROM normalized_categories
                    WHERE category_id = %s
                    """,
                    (cache_key,),
                )
                row = cursor.fetchone()
        except Exception as exc:
            raise RuntimeError(
                f"Could not load Nutri-Score category type for category_id {cache_key}: {exc}"
            ) from exc

        if row is None:
            raise LookupError(f"No normalized category exists for category_id {cache_key}.")

        stored_type = (
            row.get("nutriscore_category_type")
            if hasattr(row, "get")
            else row[0]
        )
        category_type = stored_type or "general"
        if category_type not in _CATEGORY_TYPE_TO_SCORING_CATEGORY:
            raise ValueError(
                f"Unsupported Nutri-Score category type {category_type!r} "
                f"for category_id {cache_key}."
            )

        self._category_type_cache[cache_key] = category_type
        return category_type

    @staticmethod
    def _determine_category(category_type: str) -> str:
        """Map the saved category type to the official scoring category."""
        return _CATEGORY_TYPE_TO_SCORING_CATEGORY[category_type]

    @staticmethod
    def _get_fvl_percentage(category_type: str) -> float:
        """Map the saved category type to its default FVN percentage."""
        return _CATEGORY_TYPE_TO_FVN_PERCENTAGE.get(category_type, 0.0)
    
    def calculate_single_product(
        self,
        energy_kj: float,
        sugars: float,
        saturated_fat: float,
        salt: float,
        protein: float,
        fiber: float = 0,
        total_fat: Optional[float] = None,
        fruits_veg_nuts: Optional[float] = None,
        category_code: Optional[str] = None,
        product_name: Optional[str] = None,
        ingredients_text: Optional[str] = None,
        has_sweeteners: Optional[bool] = None,
        category_id: Optional[int] = None,
        product_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Calculate Nutri-Score for a single product using 2024 algorithm.
        
        Args:
            energy_kj: Energy in kJ/100g
            sugars: Sugars in g/100g
            saturated_fat: Saturated fat in g/100g
            salt: Salt in g/100g
            protein: Protein in g/100g
            fiber: Fiber in g/100g (default: 0)
            total_fat: Total fat in g/100g (needed for oils/fats calculation)
            fruits_veg_nuts: Explicit fruits/vegetables/legumes percentage, including zero.
                None loads the product override if product_id is supplied, otherwise the category default.
            category_code: Retained product metadata; it does not affect classification.
            product_name: Product name (for sweetener detection)
            ingredients_text: Ingredients list (for sweetener detection)
            has_sweeteners: Override sweetener detection (True/False/None=auto)
            category_id: Required normalized category ID used to load the saved type.
        
        Returns:
            Dictionary with score, grade, and detailed breakdown
        """
        try:
            category_type = self._get_category_type(category_id)
            ns_category = self._determine_category(category_type)
            
            fvl_pct = fruits_veg_nuts
            if fvl_pct is None and product_id is not None:
                with self.connection.cursor() as cur:
                    cur.execute(
                        "SELECT fruit_veg_legume_percent FROM nutritionfacts WHERE product_id = %s",
                        (product_id,),
                    )
                    row = cur.fetchone()
                    if row is not None:
                        fvl_pct = (
                            row.get("fruit_veg_legume_percent")
                            if isinstance(row, dict) else row[0]
                        )
            fvl_pct = validate_fvl_percentage(fvl_pct)
            fvl_source = "manual" if fvl_pct is not None else "category"
            if fvl_pct is None:
                fvl_pct = self._get_fvl_percentage(category_type)
            
            if has_sweeteners is None and ns_category == 'beverage':
                has_sweeteners = self._detect_sweeteners(product_name, ingredients_text)
            else:
                has_sweeteners = has_sweeteners or False
            
            result = calculate_nutriscore_2024(
                category=ns_category,
                energy_kj=energy_kj or 0,
                sugars_g=sugars or 0,
                sat_fat_g=saturated_fat or 0,
                salt_g=salt or 0,
                protein_g=protein or 0,
                fiber_g=fiber or 0,
                fvl_pct=fvl_pct,
                total_fat_g=total_fat,
                has_sweeteners=has_sweeteners
            )
            
            return {
                'success': True,
                'score': result['score'],
                'grade': result['grade'],
                'n_points': result['n_points'],
                'p_points': result['p_points'],
                'protein_status': result['protein_status'],
                'components': result['components'],
                'classification': {
                    'category_id': category_id,
                    'category_type': category_type,
                    'nutriscore_category': ns_category,
                    'is_beverage': ns_category == 'beverage',
                    'is_fat_oil_nut': ns_category == 'fats_oils_nuts',
                    'is_cheese': ns_category == 'cheese',
                    'is_red_meat': ns_category == 'red_meat',
                    'fruits_veg_nuts_percent': fvl_pct,
                    'fruit_veg_legume_source': fvl_source,
                    'has_sweeteners': has_sweeteners
                }
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def batch_calculate(self, products: list) -> list:
        """
        Calculate Nutri-Score for multiple products.
        
        Args:
            products: List of dicts with keys matching calculate_single_product params
        
        Returns:
            List of results with product_id and score info
        """
        results = []
        for product in products:
            product_id = product.get('product_id')
            result = self.calculate_single_product(
                energy_kj=product.get('energy_kj', 0),
                sugars=product.get('sugars', 0),
                saturated_fat=product.get('saturated_fat', 0),
                salt=product.get('salt', 0),
                protein=product.get('protein', 0),
                fiber=product.get('fiber', 0),
                total_fat=product.get('total_fat'),
                fruits_veg_nuts=product.get('fruits_veg_nuts'),
                category_code=product.get('category_code'),
                product_name=product.get('product_name'),
                ingredients_text=product.get('ingredients_text'),
                has_sweeteners=product.get('has_sweeteners'),
                category_id=product.get('category_id'),
                product_id=product_id,
            )
            result['product_id'] = product_id
            results.append(result)
        return results


def convert_salt_to_sodium(salt: float) -> float:
    """Convert salt (g) to sodium (mg). Legacy function for backwards compatibility."""
    return salt * 400


def calculate_nutriscore(
    energy_kj: float,
    sugars: float,
    saturated_fat: float,
    sodium: float,
    protein: float,
    fiber: float = 0,
    fruits_veg_nuts: float = 0,
    is_beverage: bool = False,
    is_fat: bool = False,
    is_cheese: bool = False
) -> Tuple[int, str, Dict[str, int]]:
    """
    Backward-compatible wrapper for legacy code.
    
    DEPRECATED: Use NutriscoreCalculator.calculate_single_product() instead.
    
    This function maintains the old interface (sodium in mg, returns tuple)
    while using the new 2024 algorithm internally.
    
    Args:
        energy_kj: Energy in kJ/100g
        sugars: Sugars in g/100g
        saturated_fat: Saturated fat in g/100g
        sodium: Sodium in mg/100g (will be converted back to salt)
        protein: Protein in g/100g
        fiber: Fiber in g/100g
        fruits_veg_nuts: % fruits/vegetables/nuts
        is_beverage: True if beverage
        is_fat: True if fat/oil
        is_cheese: True if cheese
    
    Returns:
        Tuple of (numeric_score, letter_grade, component_scores)
    """
    salt_g = sodium / 400 if sodium else 0
    
    if is_beverage:
        category = 'beverage'
    elif is_fat:
        category = 'fats_oils_nuts'
    elif is_cheese:
        category = 'cheese'
    else:
        category = 'general'
    
    result = calculate_nutriscore_2024(
        category=category,
        energy_kj=energy_kj or 0,
        sugars_g=sugars or 0,
        sat_fat_g=saturated_fat or 0,
        salt_g=salt_g,
        protein_g=protein or 0,
        fiber_g=fiber or 0,
        fvl_pct=fruits_veg_nuts or 0,
        total_fat_g=None,
        has_sweeteners=False
    )
    
    components = {
        'negative_points': result['n_points'],
        'positive_points': result['p_points'],
        'energy_points': result['components']['energy_points'],
        'sugars_points': result['components']['sugar_points'],
        'saturated_fat_points': result['components']['satfat_points'],
        'sodium_points': result['components']['salt_points'],
        'protein_points': result['components']['protein_points'],
        'fiber_points': result['components']['fiber_points'],
        'fvn_points': result['components']['fvl_points']
    }
    
    return result['score'], result['grade'], components


if __name__ == '__main__':
    print("Nutri-Score 2024 Calculator - Test Examples")
    print("=" * 70)
    
    calculator = NutriscoreCalculator()
    
    print("\n1. High-fiber cereal (General category):")
    result = calculator.calculate_single_product(
        energy_kj=1801, sugars=24, saturated_fat=0.5, salt=0.3,
        protein=13, fiber=16, category_code="SH-4-1-1"
    )
    print(f"   Grade: {result['grade']}, Score: {result['score']}")
    print(f"   N={result['n_points']}, P={result['p_points']}, Protein: {result['protein_status']}")
    
    print("\n2. Camembert cheese (Cheese category - protein not blocked):")
    result = calculator.calculate_single_product(
        energy_kj=1200, sugars=0.5, saturated_fat=18, salt=1.5,
        protein=20, fiber=0, category_code="SH-11-9-27"
    )
    print(f"   Grade: {result['grade']}, Score: {result['score']}")
    print(f"   N={result['n_points']}, P={result['p_points']}, Protein: {result['protein_status']}")
    
    print("\n3. Olive oil (Fats/Oils category - uses sat/fat ratio):")
    result = calculator.calculate_single_product(
        energy_kj=3700, sugars=0, saturated_fat=14, salt=0,
        protein=0, fiber=0, total_fat=100, category_code="SH-4-3-15"
    )
    print(f"   Grade: {result['grade']}, Score: {result['score']}")
    print(f"   N={result['n_points']}, P={result['p_points']}")
    print(f"   Category: {result['classification']['nutriscore_category']}")
    
    print("\n4. Diet Cola (Beverage with sweeteners - +4 penalty):")
    result = calculator.calculate_single_product(
        energy_kj=4, sugars=0, saturated_fat=0, salt=0,
        protein=0, fiber=0, category_code="SH-5-1-1",
        product_name="Coca-Cola Zero", has_sweeteners=True
    )
    print(f"   Grade: {result['grade']}, Score: {result['score']}")
    print(f"   N={result['n_points']} (includes +4 sweetener), P={result['p_points']}")
    
    print("\n5. Water (Beverage - only A-grade beverage):")
    result = calculator.calculate_single_product(
        energy_kj=0, sugars=0, saturated_fat=0, salt=0,
        protein=0, fiber=0, category_code="SH-5-1-1",
        product_name="Mineral water", has_sweeteners=False
    )
    print(f"   Grade: {result['grade']}, Score: {result['score']}")
    
    print("\n6. Beef steak (Red Meat - protein capped at 2):")
    result = calculator.calculate_single_product(
        energy_kj=800, sugars=0, saturated_fat=5, salt=0.2,
        protein=25, fiber=0, category_code="SH-6-15-41"  # Liellopa un teļa gaļa
    )
    print(f"   Grade: {result['grade']}, Score: {result['score']}")
    print(f"   N={result['n_points']}, P={result['p_points']}, Protein: {result['protein_status']}")
    
    print("\n7. Fresh apple (Fruits - 100% FVL):")
    result = calculator.calculate_single_product(
        energy_kj=218, sugars=10.4, saturated_fat=0.03, salt=0.001,
        protein=0.3, fiber=2.4, category_code="SH-2-1-2"
    )
    print(f"   Grade: {result['grade']}, Score: {result['score']}")
    print(f"   FVL%: {result['classification']['fruits_veg_nuts_percent']}")
    
    print("\n" + "=" * 70)
    print("All tests completed successfully!")
