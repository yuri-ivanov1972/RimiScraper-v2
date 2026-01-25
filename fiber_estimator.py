"""
Fiber Estimation Module

Estimates fiber content for products based on category defaults and product name exceptions.
This is used to improve Nutri-Score accuracy when fiber data is not scraped from Rimi.

Logic:
1. If product already has fiber > 0 from scraping/USDA, skip (is_fiber_correct remains TRUE)
2. Check if product name matches any exception keywords (overrides category default)
3. Otherwise use category default fiber value
4. IMPORTANT: Estimated fiber keeps is_fiber_correct = FALSE until manually verified
   - is_fiber_correct = TRUE only for: scraped fiber, USDA data, or manual entry
   - is_fiber_correct = FALSE for: missing/null fiber, estimated values, unverified data
"""

CATEGORY_FIBER_DEFAULTS = {
    "SH-11-10-1": 0.5,
    "SH-11-10-2": 0.8,
    "SH-11-10-3": 1.2,
    "SH-11-10-4": 0.2,
    "SH-11-10-5": 0.0,
    "SH-11-1-1": 0.0,
    "SH-11-1-2": 0.0,
    "SH-11-2-3": 0.0,
    "SH-11-2-4": 0.0,
    "SH-11-2-5": 0.0,
    "SH-11-2-6": 0.1,
    "SH-11-2-7": 0.0,
    "SH-11-3-8": 0.0,
    "SH-11-3-9": 0.0,
    "SH-11-4-10": 0.0,
    "SH-11-4-11": 0.0,
    "SH-11-4-12": 0.0,
    "SH-11-5-1": 0.0,
    "SH-11-5-3": 0.0,
    "SH-11-5-5": 0.0,
    "SH-11-6-14": 0.0,
    "SH-11-6-16": 0.0,
    "SH-11-6-17": 0.0,
    "SH-11-6-18": 0.0,
    "SH-11-6-19": 0.0,
    "SH-11-6-20": 0.0,
    "SH-11-7-16": 0.0,
    "SH-11-7-17": 0.0,
    "SH-11-7-18": 0.0,
    "SH-11-7-19": 0.0,
    "SH-11-8-1": 0.0,
    "SH-11-8-2": 0.0,
    "SH-11-8-21": 0.0,
    "SH-11-8-22": 0.0,
    "SH-11-8-23": 0.0,
    "SH-11-8-24": 0.0,
    "SH-11-9-25": 0.0,
    "SH-11-9-26": 0.0,
    "SH-11-9-27": 0.0,
    "SH-11-9-28": 0.0,
    "SH-11-9-29": 0.0,
    "SH-11-9-30": 0.0,
    "SH-11-9-31": 0.0,
    "SH-11-9-32": 0.0,
    "SH-12-1-1": 0.0,
    "SH-12-1-2": 0.1,
    "SH-12-1-3": 0.1,
    "SH-12-1-4": 0.2,
    "SH-12-3-6": 0.0,
    "SH-12-3-7": 0.0,
    "SH-12-3-8": 0.0,
    "SH-12-3-9": 0.5,
    "SH-12-4-10": 3.5,
    "SH-12-4-11": 2.8,
    "SH-12-4-12": 2.2,
    "SH-12-5-14": 2.0,
    "SH-12-5-15": 1.8,
    "SH-12-5-16": 2.0,
    "SH-12-5-17": 1.5,
    "SH-13-10-24": 2.5,
    "SH-13-10-25": 1.0,
    "SH-13-10-26": 0.0,
    "SH-13-10-27": 0.0,
    "SH-13-10-28": 0.5,
    "SH-13-10-30": 0.2,
    "SH-13-10-31": 2.5,
    "SH-13-10-32": 2.0,
    "SH-13-10-33": 3.0,
    "SH-13-10-34": 0.0,
    "SH-13-10-35": 0.0,
    "SH-13-14-51": 0.0,
    "SH-13-14-53": 3.0,
    "SH-13-14-54": 8.0,
    "SH-13-16-57": 1.5,
    "SH-13-16-59": 1.5,
    "SH-13-16-60": 4.0,
    "SH-13-2-2": 0.5,
    "SH-13-2-3": 0.0,
    "SH-13-2-5": 2.0,
    "SH-13-3-6": 2.0,
    "SH-13-3-7": 1.8,
    "SH-13-3-8": 2.2,
    "SH-13-4-10": 3.5,
    "SH-13-4-11": 3.0,
    "SH-13-4-12": 4.0,
    "SH-13-4-9": 6.0,
    "SH-13-6-1": 0.0,
    "SH-13-6-2": 1.0,
    "SH-13-9-17": 5.0,
    "SH-13-9-18": 7.5,
    "SH-13-9-20": 8.0,
    "SH-13-9-21": 6.5,
    "SH-13-9-23": 7.0,
    "SH-16-1": 4.5,
    "SH-16-2-1": 2.5,
    "SH-16-2-2": 3.0,
    "SH-16-2-3": 0.5,
    "SH-2-1-2": 2.4,
    "SH-2-1-3": 2.6,
    "SH-2-1-4": 2.4,
    "SH-2-1-5": 2.5,
    "SH-2-1-6": 0.5,
    "SH-2-1-7": 1.8,
    "SH-2-1-9": 4.0,
    "SH-2-2-10": 2.8,
    "SH-2-2-12": 1.2,
    "SH-2-2-13": 2.5,
    "SH-2-2-14": 4.5,
    "SH-2-2-16": 2.0,
    "SH-2-2-17": 2.5,
    "SH-2-2-18": 2.2,
    "SH-2-2-19": 1.8,
    "SH-2-2-20": 2.5,
    "SH-2-2-9": 1.5,
    "SH-4-10-55": 2.5,
    "SH-4-10-56": 1.0,
    "SH-4-10-57": 2.5,
    "SH-4-10-58": 1.5,
    "SH-4-10-59": 2.5,
    "SH-4-10-60": 3.0,
    "SH-4-10-61": 2.2,
    "SH-4-10-62": 1.8,
    "SH-4-10-63": 2.0,
    "SH-4-10-64": 1.5,
    "SH-4-10-65": 1.0,
    "SH-4-10-66": 6.5,
    "SH-4-10-67": 1.2,
    "SH-4-10-68": 5.0,
    "SH-4-10-69": 0.0,
    "SH-4-10-70": 3.0,
    "SH-4-1-1": 1.0,
    "SH-4-11-71": 3.0,
    "SH-4-11-72": 3.0,
    "SH-4-11-73": 3.0,
    "SH-4-11-74": 3.0,
    "SH-4-11-75": 2.5,
    "SH-4-11-76": 7.0,
    "SH-4-1-2": 2.0,
    "SH-4-12-77": 1.5,
    "SH-4-12-78": 1.0,
    "SH-4-12-79": 2.0,
    "SH-4-12-80": 1.2,
    "SH-4-12-81": 2.5,
    "SH-4-12-82": 0.5,
    "SH-4-12-83": 2.0,
    "SH-4-12-84": 0.8,
    "SH-4-12-85": 2.0,
    "SH-4-1-3": 6.0,
    "SH-4-13-86": 5.0,
    "SH-4-13-87": 0.0,
    "SH-4-13-88": 2.7,
    "SH-4-13-89": 3.0,
    "SH-4-13-90": 12.0,
    "SH-4-1-4": 1.0,
    "SH-4-14-91": 2.0,
    "SH-4-14-92": 1.5,
    "SH-4-14-93": 0.0,
    "SH-4-14-94": 1.5,
    "SH-4-14-95": 3.0,
    "SH-4-14-96": 2.0,
    "SH-4-14-97": 0.5,
    "SH-4-14-98": 1.5,
    "SH-4-1-5": 0.0,
    "SH-4-15-100": 11.0,
    "SH-4-15-103": 15.0,
    "SH-4-15-104": 15.0,
    "SH-4-15-99": 8.0,
    "SH-4-16": 1.3,
    "SH-4-17-107": 3.0,
    "SH-4-17-108": 3.0,
    "SH-4-17-109": 6.0,
    "SH-4-17-110": 2.0,
    "SH-4-17-111": 4.0,
    "SH-4-18-1": 5.0,
    "SH-4-18-2": 1.0,
    "SH-4-18-3": 0.0,
    "SH-4-19-115": 0.0,
    "SH-4-19-116": 0.0,
    "SH-4-19-117": 0.0,
    "SH-4-19-118": 0.0,
    "SH-4-19-119": 0.0,
    "SH-4-19-120": 0.0,
    "SH-4-2-7": 5.0,
    "SH-4-2-8": 8.0,
    "SH-4-2-9": 6.0,
    "SH-4-3-11": 0.0,
    "SH-4-3-12": 0.0,
    "SH-4-3-13": 0.0,
    "SH-4-3-14": 0.0,
    "SH-4-3-15": 0.0,
    "SH-4-3-16": 0.0,
    "SH-4-3-17": 0.0,
    "SH-4-3-18": 0.0,
    "SH-4-3-19": 0.0,
    "SH-4-3-20": 0.0,
    "SH-4-4-21": 0.0,
    "SH-4-4-22": 0.0,
    "SH-4-4-23": 0.5,
    "SH-4-4-24": 0.0,
    "SH-4-4-25": 0.0,
    "SH-4-4-26": 0.0,
    "SH-4-5-27": 7.0,
    "SH-4-5-28": 10.0,
    "SH-4-5-29": 10.0,
    "SH-4-5-30": 3.5,
    "SH-4-6-31": 10.0,
    "SH-4-6-32": 7.0,
    "SH-4-6-33": 8.0,
    "SH-4-6-34": 9.0,
    "SH-4-6-35": 4.0,
    "SH-4-7-38": 0.0,
    "SH-4-7-39": 0.0,
    "SH-4-7-40": 0.0,
    "SH-4-7-41": 0.0,
    "SH-4-7-42": 0.0,
    "SH-4-7-43": 0.0,
    "SH-4-7-44": 30.0,
    "SH-4-9-48": 0.0,
    "SH-4-9-49": 0.0,
    "SH-4-9-50": 0.0,
    "SH-4-9-51": 0.0,
    "SH-4-9-53": 0.5,
    "SH-4-9-54": 0.0,
    "SH-5-1-1": 0.0,
    "SH-5-11-1": 1.5,
    "SH-5-11-2": 1.8,
    "SH-5-1-2": 0.0,
    "SH-5-12-18": 0.0,
    "SH-5-12-19": 0.0,
    "SH-5-12-20": 0.0,
    "SH-5-1-3": 0.0,
    "SH-5-4-5": 0.0,
    "SH-5-4-6": 0.0,
    "SH-5-4-7": 0.0,
    "SH-5-4-8": 0.0,
    "SH-5-4-9": 0.0,
    "SH-5-6-1": 0.0,
    "SH-5-6-2": 0.0,
    "SH-5-7-12": 0.0,
    "SH-5-7-13": 0.0,
    "SH-5-8-1": 0.2,
    "SH-5-8-2": 0.2,
    "SH-5-8-3": 0.3,
    "SH-5-8-4": 0.8,
    "SH-5-8-5": 0.2,
    "SH-5-8-6": 0.2,
    "SH-6-10-26": 0.0,
    "SH-6-10-27": 0.0,
    "SH-6-11": 0.0,
    "SH-6-1-1": 0.0,
    "SH-6-1-2": 0.0,
    "SH-6-13-1": 0.0,
    "SH-6-13-2": 2.0,
    "SH-6-13-3": 0.0,
    "SH-6-14-32": 0.0,
    "SH-6-14-33": 0.0,
    "SH-6-14-34": 0.0,
    "SH-6-14-35": 0.0,
    "SH-6-14-36": 0.0,
    "SH-6-14-37": 0.0,
    "SH-6-14-38": 0.0,
    "SH-6-14-39": 1.0,
    "SH-6-15-40": 0.0,
    "SH-6-15-41": 0.0,
    "SH-6-15-42": 0.0,
    "SH-6-15-5": 0.0,
    "SH-6-15-6": 0.0,
    "SH-6-16-45": 0.0,
    "SH-6-16-46": 0.0,
    "SH-6-17-48": 0.0,
    "SH-6-17-49": 0.0,
    "SH-6-18": 0.0,
    "SH-6-19-51": 0.0,
    "SH-6-19-52": 0.0,
    "SH-6-20-4": 1.5,
    "SH-6-21": 0.0,
    "SH-6-2-1": 0.0,
    "SH-6-2-3": 0.0,
    "SH-6-2-4": 0.0,
    "SH-6-2-5": 0.0,
    "SH-6-5-1": 0.0,
    "SH-6-5-2": 0.5,
    "SH-6-5-3": 0.5,
    "SH-6-5-4": 0.0,
    "SH-6-5-5": 1.5,
    "SH-6-7-12": 0.8,
    "SH-6-7-13": 2.0,
    "SH-6-7-15": 1.0,
    "SH-6-7-16": 1.5,
    "SH-6-7-18": 2.0,
    "SH-6-7-19": 1.2,
    "SH-6-7-21": 1.5,
    "SH-6-9-14": 0.0,
    "SH-6-9-22": 0.0,
    "SH-6-9-23": 0.0,
    "SH-6-9-24": 0.0,
    "SH-6-9-25": 0.0,
    "SH-7-1-1": 0.5,
    "SH-7-1-10": 1.5,
    "SH-7-1-11": 0.5,
    "SH-7-1-12": 1.5,
    "SH-7-1-3": 1.0,
    "SH-7-1-5": 0.5,
    "SH-7-1-9": 1.0,
    "SH-7-2-14": 2.4,
    "SH-7-2-15": 3.0,
    "SH-7-2-17": 6.0,
    "SH-7-2-19": 2.0,
    "SH-7-2-20": 3.5,
    "SH-7-2-21": 4.5,
    "SH-7-2-23": 2.2,
    "SH-7-2-25": 8.5,
    "SH-7-2-27": 4.0,
    "SH-7-2-28": 3.0,
}

EXCEPTION_RULES = [
    {
        "category_prefix": "SH-4-16",
        "keywords": ["Brūnie", "Integrālie", "Melnie"],
        "fiber": 3.5,
        "reason": "Whole grain rice has ~3x more fiber than white"
    },
    {
        "category_prefix": "SH-4-11",
        "keywords": ["Pilngraudu"],
        "fiber": 7.0,
        "reason": "Whole grain pasta - huge impact on Nutri-Score"
    },
    {
        "category_prefix": "SH-13-14",
        "keywords": ["70%", "85%", "Melnā"],
        "fiber": 10.0,
        "reason": "Dark chocolate is a fiber powerhouse"
    },
    {
        "category_prefix": "SH-7-2-20",
        "keywords": ["Sēklu", "Ar sēklām"],
        "fiber": 6.0,
        "reason": "Seeds add healthy fats and fiber"
    },
    {
        "category_prefix": "SH-11-2-6",
        "keywords": ["Musli", "Linsēklas"],
        "fiber": 1.5,
        "reason": "Standard yogurt is 0, but added grains change the score"
    },
    {
        "category_prefix": "SH-4-10-70",
        "keywords": ["Zemesriekstu sviests"],
        "fiber": 6.0,
        "reason": "Pure nut butters are much higher than cocoa creams"
    },
]


def get_category_fiber_default(category_code: str) -> float:
    """
    Get fiber default for a category.
    Tries exact match first, then checks parent categories.
    """
    if not category_code:
        return 0.0
    
    if category_code in CATEGORY_FIBER_DEFAULTS:
        return CATEGORY_FIBER_DEFAULTS[category_code]
    
    parts = category_code.split('-')
    for i in range(len(parts) - 1, 0, -1):
        parent_code = '-'.join(parts[:i])
        if parent_code in CATEGORY_FIBER_DEFAULTS:
            return CATEGORY_FIBER_DEFAULTS[parent_code]
    
    return 0.0


def check_exception_rules(product_name: str, category_code: str) -> tuple[float | None, str | None]:
    """
    Check if product matches any exception rules.
    Returns (fiber_value, reason) if matched, (None, None) otherwise.
    """
    if not product_name or not category_code:
        return None, None
    
    product_name_lower = product_name.lower()
    
    for rule in EXCEPTION_RULES:
        if not category_code.startswith(rule["category_prefix"]):
            continue
        
        for keyword in rule["keywords"]:
            if keyword.lower() in product_name_lower:
                return rule["fiber"], rule["reason"]
    
    return None, None


def estimate_fiber(product_name: str, category_code: str, current_fiber: float | None) -> tuple[float, str, bool]:
    """
    Estimate fiber content for a product.
    
    Args:
        product_name: Product name for exception matching
        category_code: Category code (e.g., SH-4-11-73)
        current_fiber: Current fiber value from database
        
    Returns:
        tuple of (fiber_value, source_description, should_update)
        - fiber_value: The fiber amount to use
        - source_description: Explanation of where value came from
        - should_update: Whether database should be updated
    """
    if current_fiber is not None and current_fiber > 0:
        return current_fiber, "Existing scraped/USDA value", False
    
    exception_fiber, exception_reason = check_exception_rules(product_name, category_code)
    if exception_fiber is not None:
        return exception_fiber, f"Exception rule: {exception_reason}", True
    
    category_fiber = get_category_fiber_default(category_code)
    return category_fiber, f"Category default for {category_code}", True


def batch_estimate_fiber(products: list[dict]) -> list[dict]:
    """
    Estimate fiber for a batch of products.
    
    Args:
        products: List of dicts with keys: product_id, name, category_code, fiber
        
    Returns:
        List of dicts with keys: product_id, name, old_fiber, new_fiber, source, should_update
    """
    results = []
    for product in products:
        new_fiber, source, should_update = estimate_fiber(
            product.get('name', ''),
            product.get('category_code', ''),
            product.get('fiber')
        )
        results.append({
            'product_id': product['product_id'],
            'name': product.get('name', ''),
            'category_code': product.get('category_code', ''),
            'old_fiber': product.get('fiber'),
            'new_fiber': new_fiber,
            'source': source,
            'should_update': should_update
        })
    return results
