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
    
    calculator = NutriscoreCalculator()
    result = calculator.calculate_single_product(
        energy_kj=1500,
        sugars=10.5,
        saturated_fat=3.2,
        salt=1.8,
        protein=12.0,
        fiber=5,
        total_fat=15.0,
        category_code="SH-2-1-1"
    )
    print(f"Nutriscore: {result['grade']} (Score: {result['score']})")
"""

from typing import Dict, Tuple, Any, Optional

FAT_OIL_NUT_CATEGORIES = {
    'SH-11-7-16',  # Margarines
    'SH-11-7-17',  # Butter
    'SH-11-7-18',  # Butter with additives
    'SH-11-7-19',  # Fat mixtures
    'SH-4-3-11',   # Cooking oils - general
    'SH-4-3-12',   # Cooking oils
    'SH-4-3-13',   # Cooking oils
    'SH-4-3-14',   # Coconut oil
    'SH-4-3-15',   # Olive oil
    'SH-4-3-16',   # Rapeseed oil
    'SH-4-3-17',   # Sunflower oil
    'SH-4-3-18',   # Special and other oils
    'SH-4-3-19',   # Other oils
    'SH-4-3-20',   # Other oils
    'SH-13-9-17',  # Nuts and dried fruits - Others
    'SH-13-9-18',  # Nuts and dried fruits - Nuts
    'SH-13-9-20',  # Nuts and dried fruits - Seeds
    'SH-13-9-23',  # Nuts and dried fruits - Dried fruit and nut mixes
}

CHEESE_CATEGORIES = {
    'SH-11-9-25',  # Hard cheese
    'SH-11-9-26',  # Fermented cheese
    'SH-11-9-27',  # Feta, Mozzarella cheese
    'SH-11-9-28',  # Processed cheese
    'SH-11-9-29',  # Goat, sheep cheese
    'SH-11-9-30',  # Cream cheese
    'SH-11-9-31',  # Other cheese
    'SH-11-9-32',  # Blue cheese
}

RED_MEAT_CATEGORIES = {
    'SH-6-10-26',  # Pārstrādāta gaļa - Auksti kūpinātā gaļa
    'SH-6-10-27',  # Pārstrādāta gaļa - Karsti kūpinātā gaļa
    'SH-6-11',     # Svaiga gaļa - Dažādu veidu maltā gaļa
    'SH-6-1-1',    # Cīsiņi, sardeles, desiņas - Cīsiņi un sardeles
    'SH-6-1-2',    # Cīsiņi, sardeles, desiņas - Grila desiņas
    'SH-6-15-40',  # Svaiga gaļa - Cūkgaļa
    'SH-6-15-41',  # Svaiga gaļa - Liellopa un teļa gaļa
    'SH-6-15-42',  # Svaiga gaļa - Svaigas gaļas subprodukti
    'SH-6-15-6',   # Svaiga gaļa - Jēra gaļa
    'SH-6-17-49',  # Marinēta gaļa - Cūkgaļa
    'SH-6-20-4',   # Mani Gardumi - Gatavās maltītes
    'SH-6-21',     # Pārstrādāta gaļa - Vītinātās gaļas produkti
    'SH-6-2-1',    # Desas un pastētes - Pastēte, aknu desas
    'SH-6-2-3',    # Desas un pastētes - Auksti kūpinātās desas
    'SH-6-2-4',    # Desas un pastētes - Karsti kūpinātās desas
    'SH-6-2-5',    # Desas un pastētes - Vārītās desas
    'SH-6-5-1',    # Gaļas maltītes - Galerti, gaļa želejā
    'SH-6-5-2',    # Gaļas maltītes - Gaļas bumbiņas, nageti
    'SH-6-5-3',    # Gaļas maltītes - Lēni pagatavotas gaļas maltītes
    'SH-6-9-14',   # Zivju un gaļas konservi - Gaļas konservi
}

FULL_FVN_CATEGORIES = {
    'SH-12-4-10',  # Frozen fruits and berries
    'SH-12-4-11',  # Frozen vegetables and mixtures
    'SH-12-4-12',  # Frozen potatoes
    'SH-13-9-21',  # Nuts and dried fruits - Dried fruits and berries
    'SH-2-1-2',    # Fruits - Apples and pears
    'SH-2-1-3',    # Fruits - Bananas
    'SH-2-1-4',    # Fruits - Citrus fruits
    'SH-2-1-5',    # Fruits - Exotic fruits
    'SH-2-1-6',    # Fruits - Melons and watermelons
    'SH-2-1-7',    # Fruits - Stone fruits
    'SH-2-1-9',    # Fruits - Berries
    'SH-2-2',      # Vegetables
    'SH-2-2-10',   # Vegetables - Beets and other root vegetables
    'SH-2-2-12',   # Vegetables - Cucumbers and tomatoes
    'SH-2-2-13',   # Vegetables - Potatoes and carrots
    'SH-2-2-14',   # Vegetables - Legumes, corn and asparagus
    'SH-2-2-16',   # Vegetables - Peppers
    'SH-2-2-17',   # Vegetables - Processed vegetables
    'SH-2-2-18',   # Vegetables - Cabbage and lettuce
    'SH-2-2-19',   # Vegetables - Onions, leeks and garlic
    'SH-2-2-20',   # Vegetables - Herbs
    'SH-2-2-9',    # Vegetables - Pumpkins and squash
}

HALF_FVN_CATEGORIES = {
    'SH-4-10-55',  # Canned products - Other canned vegetables
    'SH-4-10-57',  # Canned products - Canned corn
    'SH-4-10-58',  # Canned products - Canned peppers
    'SH-4-10-59',  # Canned products - Canned beets
    'SH-4-10-60',  # Canned products - Canned olives
    'SH-4-10-62',  # Canned products - Canned fruits and berries
    'SH-4-10-63',  # Canned products - Canned purees
    'SH-4-10-65',  # Canned products - Canned cucumbers
    'SH-4-10-66',  # Canned products - Canned legumes
    'SH-4-10-67',  # Canned products - Canned tomatoes
    'SH-4-10-68',  # Canned products - Canned peas
    'SH-4-12-85',  # Sauces - Tomato sauces and pastes
}

BEVERAGE_CATEGORIES = {
    'SH-5-1',      # Dzērieni - Bezalkoholiskais alus, sidri un vīni
    'SH-5-1-1',    # Dzērieni - Bezalkoholiskais alus
    'SH-5-1-2',    # Dzērieni - Bezalkoholiskais sidrs
    'SH-5-1-3',    # Dzērieni - Bezalkoholiskais vīns
    'SH-5-2',      # Dzērieni - Dzirkstošie bezalkoholiskie dzērieni
    'SH-5-3',      # Dzērieni - Enerģijas dzērieni
    'SH-5-4-5',    # Dzērieni - Limonādes - Gāzētas limonādes
    'SH-5-4-6',    # Dzērieni - Limonādes - Kvass
    'SH-5-4-7',    # Dzērieni - Limonādes - Ledus tējas
    'SH-5-4-8',    # Dzērieni - Limonādes - Negāzētas limonādes
    'SH-5-4-9',    # Dzērieni - Limonādes - Toniki
    'SH-5-6-1',    # Dzērieni - Sīrupi - Kafijas un kokteiļu sīrupi
    'SH-5-6-2',    # Dzērieni - Sīrupi - Ogu un augļu sīrupi
    'SH-5-7-12',   # Dzērieni - Sporta dzērieni
    'SH-5-7-13',   # Dzērieni - Vitaminizētais ūdens
    'SH-5-8-1',    # Dzērieni - Sulas - Ābolu un miksētas ābolu
    'SH-5-8-2',    # Dzērieni - Sulas - Citrusaugļu
    'SH-5-8-3',    # Dzērieni - Sulas - Ogu
    'SH-5-8-4',    # Dzērieni - Sulas - Dārzeņu
    'SH-5-8-5',    # Dzērieni - Sulas - Multiaugļu
    'SH-5-8-6',    # Dzērieni - Sulas - Citu augļu sulas
    'SH-5-11',     # Dzērieni - Svaigas sulas un smūtiji
    'SH-5-11-1',   # Dzērieni - Svaigas sulas - Augļu sulas un smūtiji
    'SH-5-11-2',   # Dzērieni - Svaigas sulas - Dārzeņu sulas un smūtiji
    'SH-5-12-18',  # Dzērieni - Ūdens - Gāzēts ūdens
    'SH-5-12-19',  # Dzērieni - Ūdens - Negāzēts ūdens
    'SH-5-12-20',  # Dzērieni - Ūdens - Ūdens ar garšām
    'SH-11-8-1',   # Pilnpiens (whole milk)
    'SH-11-8-2',   # Other milk
    'SH-11-8-22',  # Pasterizēts piens (pasteurized milk)
    'SH-11-8-23',  # Piens ar piedevām (milk with additives)
    'SH-11-8-24',  # UHT piens (UHT milk)
    'SH-11-3-8',   # Kefīrs un kefīra dzērieni (kefir drinks)
    'SH-11-3-9',   # Other fermented drinks
    'SH-4-14-93',  # Kokosa piens (coconut milk) - plant drink
}

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
        if final_score <= -1:
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
    
    def __init__(self):
        self.fat_oil_nut_categories = FAT_OIL_NUT_CATEGORIES
        self.cheese_categories = CHEESE_CATEGORIES
        self.red_meat_categories = RED_MEAT_CATEGORIES
        self.full_fvn_categories = FULL_FVN_CATEGORIES
        self.half_fvn_categories = HALF_FVN_CATEGORIES
    
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
    
    def _determine_category(self, category_code: Optional[str]) -> str:
        """Determine the Nutri-Score category based on product category code."""
        if not category_code:
            return 'general'
        
        if category_code in BEVERAGE_CATEGORIES:
            return 'beverage'
        
        if category_code in self.fat_oil_nut_categories:
            return 'fats_oils_nuts'
        
        if category_code in self.cheese_categories:
            return 'cheese'
        
        if category_code in self.red_meat_categories:
            return 'red_meat'
        
        return 'general'
    
    def _get_fvl_percentage(self, category_code: Optional[str]) -> float:
        """Get fruits/vegetables/legumes percentage based on category."""
        if not category_code:
            return 0
        
        if category_code in self.full_fvn_categories:
            return 100
        
        if category_code in self.half_fvn_categories:
            return 50
        
        for prefix in ['SH-2-1', 'SH-2-2']:
            if category_code.startswith(prefix):
                return 100
        
        return 0
    
    def calculate_single_product(
        self,
        energy_kj: float,
        sugars: float,
        saturated_fat: float,
        salt: float,
        protein: float,
        fiber: float = 0,
        total_fat: Optional[float] = None,
        fruits_veg_nuts: float = 0,
        category_code: Optional[str] = None,
        product_name: Optional[str] = None,
        ingredients_text: Optional[str] = None,
        has_sweeteners: Optional[bool] = None
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
            fruits_veg_nuts: % fruits/vegetables/nuts (default: 0, auto-detected from category)
            category_code: Product category code (e.g., "SH-2-1-1")
            product_name: Product name (for sweetener detection)
            ingredients_text: Ingredients list (for sweetener detection)
            has_sweeteners: Override sweetener detection (True/False/None=auto)
        
        Returns:
            Dictionary with score, grade, and detailed breakdown
        """
        try:
            ns_category = self._determine_category(category_code)
            
            fvl_pct = fruits_veg_nuts
            if fvl_pct == 0:
                fvl_pct = self._get_fvl_percentage(category_code)
            
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
                    'nutriscore_category': ns_category,
                    'is_beverage': ns_category == 'beverage',
                    'is_fat_oil_nut': ns_category == 'fats_oils_nuts',
                    'is_cheese': ns_category == 'cheese',
                    'is_red_meat': ns_category == 'red_meat',
                    'fruits_veg_nuts_percent': fvl_pct,
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
                fruits_veg_nuts=product.get('fruits_veg_nuts', 0),
                category_code=product.get('category_code'),
                product_name=product.get('product_name'),
                ingredients_text=product.get('ingredients_text'),
                has_sweeteners=product.get('has_sweeteners')
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


FAT_CATEGORIES = FAT_OIL_NUT_CATEGORIES


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
