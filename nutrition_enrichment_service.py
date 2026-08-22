"""
Nutrition Enrichment Service

Orchestrates the nutrition data enrichment workflow:
1. Get products needing enrichment from database
2. Translate Latvian names to English
3. Search USDA for nutrition data
4. Present matches for manual review
5. Save approved data to database
"""

import os
import psycopg2
from psycopg2.extras import RealDictCursor
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from food_translator import FoodTranslator, TranslationResult
from usda_enrichment import USDAClient, USDAFoodMatch, NutritionData
from nutriscore_calculator import NutriscoreCalculator


@dataclass
class ProductForEnrichment:
    """Product that needs nutrition data enrichment"""
    product_id: int
    sku: str
    name: str
    category_id: Optional[int] = None
    category_name: Optional[str] = None
    current_nutrition: Optional[Dict] = None
    
    def to_dict(self) -> Dict:
        return {
            'product_id': self.product_id,
            'sku': self.sku,
            'name': self.name,
            'category_id': self.category_id,
            'category_name': self.category_name,
            'current_nutrition': self.current_nutrition
        }


@dataclass 
class EnrichmentMatch:
    """A product with its USDA match options for review"""
    product: ProductForEnrichment
    translation: TranslationResult
    usda_options: List[USDAFoodMatch] = field(default_factory=list)
    selected_index: int = 0
    status: str = 'pending'
    
    @property
    def usda_match(self) -> Optional[USDAFoodMatch]:
        """Get the currently selected USDA match"""
        if self.usda_options and 0 <= self.selected_index < len(self.usda_options):
            return self.usda_options[self.selected_index]
        return None
    
    def select_option(self, index: int):
        """Select a different USDA match option"""
        if 0 <= index < len(self.usda_options):
            self.selected_index = index
    
    def to_dict(self) -> Dict:
        return {
            'product': self.product.to_dict(),
            'translation': self.translation.to_dict(),
            'usda_options': [opt.to_dict() for opt in self.usda_options],
            'selected_index': self.selected_index,
            'usda_match': self.usda_match.to_dict() if self.usda_match else None,
            'status': self.status
        }


@dataclass
class EnrichmentBatch:
    """A batch of products for enrichment review"""
    matches: List[EnrichmentMatch] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    
    @property
    def total(self) -> int:
        return len(self.matches)
    
    @property
    def pending(self) -> int:
        return sum(1 for m in self.matches if m.status == 'pending')
    
    @property
    def approved(self) -> int:
        return sum(1 for m in self.matches if m.status == 'approved')
    
    @property
    def skipped(self) -> int:
        return sum(1 for m in self.matches if m.status == 'skipped')
    
    @property
    def no_match(self) -> int:
        return sum(1 for m in self.matches if m.status == 'no_match')


class NutritionEnrichmentService:
    """
    Service for enriching product nutrition data from USDA
    
    Usage:
        service = NutritionEnrichmentService()
        
        # Get products needing enrichment
        products = service.get_products_needing_enrichment(limit=20)
        
        # Process batch
        batch = service.process_batch(products)
        
        # Review and approve
        for match in batch.matches:
            if match.usda_match:
                service.approve_match(match)
            else:
                service.skip_match(match)
    """
    
    def __init__(self, status_callback=None):
        self.status_callback = status_callback or print
        self.db_url = os.environ.get('DATABASE_URL')
        
        google_key = os.environ.get('GOOGLE_TRANSLATE_API_KEY')
        self.translator = FoodTranslator(google_api_key=google_key, status_callback=self.status_callback)
        self.usda_client = USDAClient(status_callback=self.status_callback)
        
    def _get_connection(self):
        """Get database connection"""
        return psycopg2.connect(self.db_url)
    
    def get_enrichment_stats(self) -> Dict[str, int]:
        """Get statistics about products needing enrichment"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT 
                        COUNT(*) FILTER (WHERE needs_enrichment = TRUE AND (enrichment_reviewed IS NULL OR enrichment_reviewed = FALSE)) as needs_enrichment,
                        COUNT(*) FILTER (WHERE enrichment_reviewed = TRUE) as reviewed,
                        COUNT(*) FILTER (WHERE nutrition_source = 'usda_api') as from_usda,
                        COUNT(*) FILTER (WHERE nutrition_source = 'rimi_scraped') as from_rimi,
                        COUNT(*) FILTER (WHERE enrichment_skipped = TRUE AND (enrichment_reviewed IS NULL OR enrichment_reviewed = FALSE)) as skipped,
                        COUNT(*) as total
                    FROM products
                """)
                row = cur.fetchone()
                return {
                    'needs_enrichment': row[0] or 0,
                    'reviewed': row[1] or 0,
                    'from_usda': row[2] or 0,
                    'from_rimi': row[3] or 0,
                    'skipped': row[4] or 0,
                    'total': row[5] or 0
                }
        finally:
            conn.close()
    
    def get_products_needing_enrichment(self, limit: int = 20, offset: int = 0) -> List[ProductForEnrichment]:
        """Get products that need nutrition data enrichment"""
        conn = self._get_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT 
                        p.product_id,
                        p.sku,
                        p.name,
                        p.category_id,
                        nc.name_lv as category_name,
                        nf.energy_kcal,
                        nf.fat_total,
                        nf.fat_saturated,
                        nf.carbs_total,
                        nf.carbs_sugars,
                        nf.protein,
                        nf.salt,
                        nf.fiber,
                        COALESCE(p.enrichment_skipped, FALSE) as enrichment_skipped
                    FROM products p
                    LEFT JOIN normalized_categories nc ON p.category_id = nc.category_id
                    LEFT JOIN nutritionfacts nf ON p.product_id = nf.product_id
                    WHERE p.needs_enrichment = TRUE
                      AND (p.enrichment_reviewed IS NULL OR p.enrichment_reviewed = FALSE)
                    ORDER BY COALESCE(p.enrichment_skipped, FALSE) ASC, p.product_id
                    LIMIT %s OFFSET %s
                """, (limit, offset))
                
                rows = cur.fetchall()
                products = []
                
                for row in rows:
                    current_nutrition = {
                        'energy_kcal': float(row['energy_kcal']) if row['energy_kcal'] else None,
                        'fat_total': float(row['fat_total']) if row['fat_total'] else None,
                        'fat_saturated': float(row['fat_saturated']) if row['fat_saturated'] else None,
                        'carbs_total': float(row['carbs_total']) if row['carbs_total'] else None,
                        'carbs_sugars': float(row['carbs_sugars']) if row['carbs_sugars'] else None,
                        'protein': float(row['protein']) if row['protein'] else None,
                        'salt': float(row['salt']) if row['salt'] else None,
                        'fiber': float(row['fiber']) if row['fiber'] else None,
                    }
                    
                    products.append(ProductForEnrichment(
                        product_id=row['product_id'],
                        sku=row['sku'],
                        name=row['name'],
                        category_id=row['category_id'],
                        category_name=row['category_name'],
                        current_nutrition=current_nutrition
                    ))
                
                self.status_callback(f"📦 Loaded {len(products)} products needing enrichment")
                return products
                
        finally:
            conn.close()
    
    def process_single_product(self, product: ProductForEnrichment, num_options: int = 5) -> EnrichmentMatch:
        """Process a single product: translate and search USDA for multiple options"""
        self.status_callback(f"\n🔄 Processing: {product.name} (SKU: {product.sku})")
        
        translation = self.translator.translate(product.name)
        
        usda_options = self.usda_client.search_and_get_top_matches(translation.english, num_options=num_options)
        
        match = EnrichmentMatch(
            product=product,
            translation=translation,
            usda_options=usda_options,
            selected_index=0,
            status='pending' if usda_options else 'no_match'
        )
        
        if usda_options:
            self.status_callback(f"✅ Found {len(usda_options)} options. Top: {usda_options[0].description} (Score: {usda_options[0].score:.1f})")
        else:
            self.status_callback(f"⚠️ No USDA match found for '{translation.english}'")
        
        return match
    
    def process_batch(self, products: List[ProductForEnrichment]) -> EnrichmentBatch:
        """Process a batch of products for enrichment"""
        batch = EnrichmentBatch()
        
        self.status_callback(f"\n{'='*50}")
        self.status_callback(f"🚀 Processing batch of {len(products)} products")
        self.status_callback(f"{'='*50}")
        
        for i, product in enumerate(products, 1):
            self.status_callback(f"\n[{i}/{len(products)}] Processing...")
            match = self.process_single_product(product)
            batch.matches.append(match)
        
        self.status_callback(f"\n{'='*50}")
        self.status_callback(f"📊 Batch complete: {batch.total} total, {batch.pending} pending, {batch.no_match} no match")
        self.status_callback(f"{'='*50}")
        
        return batch
    
    def search_custom_term(self, product: ProductForEnrichment, search_term: str, num_options: int = 5) -> EnrichmentMatch:
        """Search USDA with a custom term provided by user"""
        self.status_callback(f"🔍 Custom search for '{search_term}'")
        
        usda_options = self.usda_client.search_and_get_top_matches(search_term, num_options=num_options)
        
        translation = TranslationResult(
            original=product.name,
            english=search_term,
            method='manual',
            confidence=1.0
        )
        
        return EnrichmentMatch(
            product=product,
            translation=translation,
            usda_options=usda_options,
            selected_index=0,
            status='pending' if usda_options else 'no_match'
        )
    
    def save_enrichment(self, match: EnrichmentMatch) -> bool:
        """Save approved enrichment data to database"""
        if not match.usda_match or not match.usda_match.nutrition:
            self.status_callback(f"❌ Cannot save: no nutrition data for {match.product.sku}")
            return False
        
        conn = self._get_connection()
        try:
            with conn.cursor() as cur:
                nutrition = match.usda_match.nutrition
                
                usda_fdc_id = match.usda_match.fdc_id
                
                cur.execute("""
                    UPDATE nutritionfacts
                    SET 
                        energy_kcal = %s,
                        energy_kj = %s,
                        fat_total = %s,
                        fat_saturated = %s,
                        carbs_total = %s,
                        carbs_sugars = %s,
                        protein = %s,
                        salt = %s,
                        fiber = %s,
                        usda_fdc_id = %s,
                        data_source_date = NOW()
                    WHERE product_id = %s
                """, (
                    nutrition.energy_kcal,
                    nutrition.energy_kj,
                    nutrition.fat_total,
                    nutrition.fat_saturated,
                    nutrition.carbs_total,
                    nutrition.carbs_sugars,
                    nutrition.protein,
                    nutrition.salt,
                    nutrition.fiber,
                    usda_fdc_id,
                    match.product.product_id
                ))
                
                if cur.rowcount == 0:
                    cur.execute("""
                        INSERT INTO nutritionfacts 
                        (product_id, energy_kcal, energy_kj, fat_total, fat_saturated, 
                         carbs_total, carbs_sugars, protein, salt, fiber, usda_fdc_id, data_source_date)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    """, (
                        match.product.product_id,
                        nutrition.energy_kcal,
                        nutrition.energy_kj,
                        nutrition.fat_total,
                        nutrition.fat_saturated,
                        nutrition.carbs_total,
                        nutrition.carbs_sugars,
                        nutrition.protein,
                        nutrition.salt,
                        nutrition.fiber,
                        usda_fdc_id
                    ))
                
                cur.execute("""
                    UPDATE products
                    SET 
                        nutrition_source = 'usda_api',
                        needs_enrichment = FALSE,
                        enrichment_reviewed = TRUE,
                        updated_at = NOW()
                    WHERE product_id = %s
                """, (match.product.product_id,))
                
                nutri_score, nutri_grade = self._calculate_nutriscore(
                    connection=conn,
                    nutrition=nutrition,
                    category_id=match.product.category_id,
                    product_name=match.product.name,
                )
                
                if nutri_score is not None:
                    cur.execute("""
                        UPDATE nutritionfacts
                        SET 
                            nutri_score_points = %s,
                            nutri_score_grade = %s
                        WHERE product_id = %s
                    """, (nutri_score, nutri_grade, match.product.product_id))
                    self.status_callback(f"📊 Nutri-Score: {nutri_grade} ({nutri_score} points)")
                
                conn.commit()
                
                match.status = 'approved'
                self.status_callback(f"✅ Saved enrichment for {match.product.sku}: {match.product.name}")
                return True
                
        except Exception as e:
            conn.rollback()
            self.status_callback(f"❌ Error saving enrichment: {str(e)}")
            return False
        finally:
            conn.close()
    
    def skip_product(self, match: EnrichmentMatch, mark_reviewed: bool = False) -> bool:
        """Skip a product - marks as skipped for later review (sorted to end of batches)"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE products
                    SET 
                        enrichment_skipped = TRUE,
                        updated_at = NOW()
                    WHERE product_id = %s
                """, (match.product.product_id,))
                conn.commit()
                
                match.status = 'skipped'
                self.status_callback(f"⏭️ Skipped: {match.product.sku} - {match.product.name}")
                return True
                
        except Exception as e:
            conn.rollback()
            self.status_callback(f"❌ Error skipping product: {str(e)}")
            return False
        finally:
            conn.close()
    
    def unskip_product(self, match: EnrichmentMatch) -> bool:
        """Unskip a product - brings it back to normal queue position"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE products
                    SET 
                        enrichment_skipped = FALSE,
                        updated_at = NOW()
                    WHERE product_id = %s
                """, (match.product.product_id,))
                conn.commit()
                
                match.status = 'pending' if match.usda_options else 'no_match'
                self.status_callback(f"🔄 Unskipped: {match.product.sku} - {match.product.name}")
                return True
                
        except Exception as e:
            conn.rollback()
            self.status_callback(f"❌ Error unskipping product: {str(e)}")
            return False
        finally:
            conn.close()
    
    def _calculate_nutriscore(
        self,
        connection,
        nutrition: NutritionData,
        category_id: Optional[int],
        product_name: Optional[str] = None,
    ) -> tuple:
        """Calculate nutri-score points and grade from nutrition data
        
        Returns:
            Tuple of (score_points, grade) or (None, None) if calculation not possible
        """
        try:
            energy_kj = nutrition.energy_kj or (nutrition.energy_kcal * 4.184 if nutrition.energy_kcal else 0)
            sugars = nutrition.carbs_sugars or 0
            saturated_fat = nutrition.fat_saturated or 0
            salt = nutrition.salt or 0
            protein = nutrition.protein or 0
            fiber = nutrition.fiber or 0
            
            if energy_kj == 0 and sugars == 0 and saturated_fat == 0:
                self.status_callback("⚠️ Insufficient data for Nutri-Score calculation")
                return (None, None)
            
            result = NutriscoreCalculator(connection).calculate_single_product(
                energy_kj=energy_kj,
                sugars=sugars,
                saturated_fat=saturated_fat,
                salt=salt,
                protein=protein,
                fiber=fiber,
                total_fat=nutrition.fat_total,
                product_name=product_name,
                category_id=category_id,
            )
            if not result.get("success"):
                self.status_callback(
                    f"⚠️ Nutri-Score calculation skipped: {result.get('error')}"
                )
                return (None, None)

            return (result["score"], result["grade"])
            
        except Exception as e:
            self.status_callback(f"⚠️ Error calculating Nutri-Score: {str(e)}")
            return (None, None)


def test_enrichment_service():
    """Test the enrichment service"""
    try:
        service = NutritionEnrichmentService()
        
        print("Testing enrichment service...\n")
        
        stats = service.get_enrichment_stats()
        print(f"Enrichment stats: {stats}\n")
        
        products = service.get_products_needing_enrichment(limit=3)
        
        if products:
            print(f"\nProcessing {len(products)} products...")
            batch = service.process_batch(products)
            
            print(f"\nBatch results:")
            for match in batch.matches:
                print(f"  - {match.product.name}")
                print(f"    Translation: {match.translation.english}")
                if match.usda_match:
                    print(f"    USDA Match: {match.usda_match.description}")
                    if match.usda_match.nutrition:
                        n = match.usda_match.nutrition
                        print(f"    Nutrition: {n.energy_kcal} kcal, {n.protein}g protein")
                else:
                    print(f"    No match found")
        else:
            print("No products need enrichment")
            
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    test_enrichment_service()
