"""
Ingredient Canonical Import Module
Handles importing ingredient categorization CSV files from Google AI Studio.

CSV Format: id|ingredient|category|type
- id: Pipe-separated list of ingredient_analysis IDs (synonyms separated by !)
- ingredient: Canonical name
- category: A (natural) or B (processed)
- type: Latvian description

First ID in each group becomes the canonical_id.
"""

import psycopg2
from psycopg2.extras import execute_values
import os
from typing import List, Dict, Tuple, Optional
import io


class IngredientCanonicalImporter:
    def __init__(self, db_connection=None):
        self.connection = db_connection
        
    def _ensure_connection(self):
        if self.connection is None or self.connection.closed:
            self.connection = psycopg2.connect(os.environ.get('DATABASE_URL'))
        return self.connection
    
    def parse_csv_content(self, content: str) -> List[Dict]:
        """Parse CSV content and return list of ingredient records."""
        lines = content.strip().split('\n')
        if not lines:
            return []
        
        records = []
        for i, line in enumerate(lines):
            if i == 0 and 'id|ingredient|category|type' in line.lower():
                continue
            
            parts = line.split('|')
            if len(parts) < 4:
                continue
            
            id_str, ingredient_name, category_code, description = parts[0], parts[1], parts[2], parts[3]
            
            ingredient_ids = [int(x.strip()) for x in id_str.split('!') if x.strip().isdigit()]
            if not ingredient_ids:
                continue
            
            ingredient_type = 'natural' if category_code.strip().upper() == 'A' else 'processed'
            
            records.append({
                'canonical_id': ingredient_ids[0],
                'synonym_ids': ingredient_ids,
                'name': ingredient_name.strip(),
                'type': ingredient_type,
                'description': description.strip()
            })
        
        return records
    
    def check_existing_mappings(self, records: List[Dict]) -> Dict:
        """Check for existing canonical entries and mappings."""
        conn = self._ensure_connection()
        
        all_ids = []
        for r in records:
            all_ids.extend(r['synonym_ids'])
        
        existing_canonical = set()
        existing_mappings = {}
        
        with conn.cursor() as cur:
            if all_ids:
                cur.execute(
                    "SELECT canonical_id FROM ingredient_canonical WHERE canonical_id = ANY(%s)",
                    (all_ids,)
                )
                existing_canonical = {row[0] for row in cur.fetchall()}
                
                cur.execute(
                    "SELECT ingredient_id, canonical_id FROM ingredient_mapping WHERE ingredient_id = ANY(%s)",
                    (all_ids,)
                )
                existing_mappings = {row[0]: row[1] for row in cur.fetchall()}
        
        return {
            'existing_canonical': existing_canonical,
            'existing_mappings': existing_mappings
        }
    
    def validate_ingredient_ids(self, records: List[Dict]) -> Dict:
        """Validate that ingredient IDs exist in ingredient_analysis."""
        conn = self._ensure_connection()
        
        all_ids = []
        for r in records:
            all_ids.extend(r['synonym_ids'])
        
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM ingredient_analysis WHERE id = ANY(%s)",
                (all_ids,)
            )
            valid_ids = {row[0] for row in cur.fetchall()}
        
        invalid_ids = set(all_ids) - valid_ids
        return {
            'valid_ids': valid_ids,
            'invalid_ids': invalid_ids
        }
    
    def import_records(self, records: List[Dict], skip_existing: bool = True) -> Dict:
        """
        Import records into ingredient_canonical and ingredient_mapping tables.
        
        Args:
            records: List of parsed ingredient records
            skip_existing: If True, skip records with existing canonical_id
            
        Returns:
            Summary of import results
        """
        conn = self._ensure_connection()
        
        validation = self.validate_ingredient_ids(records)
        existing_check = self.check_existing_mappings(records)
        
        imported_canonical = 0
        imported_mappings = 0
        skipped_canonical = 0
        skipped_mappings = 0
        errors = []
        
        with conn.cursor() as cur:
            for record in records:
                canonical_id = record['canonical_id']
                
                if canonical_id not in validation['valid_ids']:
                    errors.append(f"Canonical ID {canonical_id} not found in ingredient_analysis")
                    continue
                
                if canonical_id in existing_check['existing_canonical']:
                    if skip_existing:
                        skipped_canonical += 1
                    else:
                        cur.execute("""
                            UPDATE ingredient_canonical 
                            SET name = %s, type = %s, description = %s, updated_at = NOW()
                            WHERE canonical_id = %s
                        """, (record['name'], record['type'], record['description'], canonical_id))
                        imported_canonical += 1
                else:
                    cur.execute("""
                        INSERT INTO ingredient_canonical (canonical_id, name, type, description)
                        VALUES (%s, %s, %s, %s)
                    """, (canonical_id, record['name'], record['type'], record['description']))
                    imported_canonical += 1
                
                for synonym_id in record['synonym_ids']:
                    if synonym_id not in validation['valid_ids']:
                        continue
                    
                    if synonym_id in existing_check['existing_mappings']:
                        if skip_existing:
                            skipped_mappings += 1
                        else:
                            cur.execute("""
                                UPDATE ingredient_mapping SET canonical_id = %s WHERE ingredient_id = %s
                            """, (canonical_id, synonym_id))
                            imported_mappings += 1
                    else:
                        cur.execute("""
                            INSERT INTO ingredient_mapping (ingredient_id, canonical_id)
                            VALUES (%s, %s)
                            ON CONFLICT (ingredient_id) DO UPDATE SET canonical_id = %s
                        """, (synonym_id, canonical_id, canonical_id))
                        imported_mappings += 1
            
            conn.commit()
        
        return {
            'imported_canonical': imported_canonical,
            'imported_mappings': imported_mappings,
            'skipped_canonical': skipped_canonical,
            'skipped_mappings': skipped_mappings,
            'invalid_ids': list(validation['invalid_ids']),
            'errors': errors
        }
    
    def refresh_materialized_view(self) -> bool:
        """Refresh the product_ingredients_display materialized view."""
        conn = self._ensure_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("REFRESH MATERIALIZED VIEW product_ingredients_display")
                conn.commit()
            return True
        except Exception as e:
            print(f"Error refreshing materialized view: {e}")
            return False
    
    def get_import_stats(self) -> Dict:
        """Get current statistics about canonical ingredients."""
        conn = self._ensure_connection()
        
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM ingredient_canonical")
            total_canonical = cur.fetchone()[0]
            
            cur.execute("SELECT type, COUNT(*) FROM ingredient_canonical GROUP BY type")
            type_counts = {row[0]: row[1] for row in cur.fetchall()}
            
            cur.execute("SELECT COUNT(*) FROM ingredient_mapping")
            total_mappings = cur.fetchone()[0]
            
            cur.execute("SELECT COUNT(*) FROM ingredient_analysis")
            total_ingredients = cur.fetchone()[0]
            
            cur.execute("""
                SELECT COUNT(*) FROM ingredient_analysis ia
                WHERE NOT EXISTS (SELECT 1 FROM ingredient_mapping im WHERE im.ingredient_id = ia.id)
            """)
            unmapped_count = cur.fetchone()[0]
        
        return {
            'total_canonical': total_canonical,
            'type_counts': type_counts,
            'total_mappings': total_mappings,
            'total_ingredients': total_ingredients,
            'unmapped_count': unmapped_count,
            'coverage_percent': round((total_mappings / total_ingredients * 100), 1) if total_ingredients > 0 else 0
        }
    
    def get_unmapped_ingredients(self, limit: int = 100) -> List[Dict]:
        """Get list of unmapped ingredients ordered by frequency."""
        conn = self._ensure_connection()
        
        with conn.cursor() as cur:
            cur.execute("""
                SELECT ia.id, ia.ingredient, ia.frequency
                FROM ingredient_analysis ia
                WHERE NOT EXISTS (SELECT 1 FROM ingredient_mapping im WHERE im.ingredient_id = ia.id)
                ORDER BY ia.frequency DESC
                LIMIT %s
            """, (limit,))
            
            return [{'id': row[0], 'ingredient': row[1], 'frequency': row[2]} for row in cur.fetchall()]
