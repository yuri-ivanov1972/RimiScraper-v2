#!/usr/bin/env python3
"""
Rule-based ingredient/nutrition consistency validation.

The validator is deliberately separate from scraping and never changes source
nutrition or ingredient records.  It consumes the normalized ingredient names
already stored in ingredient_analysis/ingredient_product_mapping and returns a
deterministic, JSON-serializable result.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence


NUTRITION_VALIDATION_CONFIG = {
    "weights": {
        "impossible_relationship": 10,
        "fat_ingredient_zero": 8,
        "sugar_ingredient_zero": 8,
        "salt_ingredient_zero": 8,
        "dairy_saturated_fat_zero": 8,
        "protein_ingredient_zero": 8,
        "strong_association_low": 5,
        "energy_inconsistent": 5,
        "salty_ingredient_low_salt": 5,
        "weak_association": 2,
        "zero_value_cluster": 5,
    },
    "thresholds": {
        "none_max": 0,
        "low_max": 4,
        "medium_max": 9,
        "energy_relative_difference": 0.20,
        "energy_absolute_difference_kcal": 50.0,
        "low_salt_grams": 0.10,
        "zero_cluster_min_fields": 3,
        "small_quantity_percent": 1.0,
    },
}


# Terms are intentionally Latvian-first.  Matching is whole-word/whole-phrase
# based after normalization, rather than a raw substring search.
INGREDIENT_KEYWORDS = {
    "dairy": (
        "piens",
        "piena",
        "pienu",
        "pienā",
        "vājpiens",
        "vājpiena",
        "pilnpiens",
        "pilnpiena",
        "krējums",
        "saldais krējums",
        "sviests",
        "sūkalas",
        "sūkalu",
        "biezpiens",
        "siers",
        "piena tauki",
        "iebiezināts piens",
        "sausais piens",
    ),
    "fat": (
        "augu eļļa",
        "augu eļļas",
        "rapšu eļļa",
        "rapšu eļļas",
        "saulespuķu eļļa",
        "saulespuķu eļļas",
        "olīveļļa",
        "olīvu eļļa",
        "kokosriekstu eļļa",
        "palmu eļļa",
        "kakao sviests",
        "sviests",
        "piena tauki",
        "augu tauki",
        "palmu tauki",
    ),
    "fat_rich": (
        "kokosriekstu eļļa",
        "kokosriekstu tauki",
        "palmu eļļa",
        "palmu tauki",
        "sviests",
        "piena tauki",
        "krējums",
        "kakao sviests",
    ),
    "sugar": (
        "cukurs",
        "cukura",
        "saharoze",
        "glikoze",
        "fruktoze",
        "dekstroze",
        "glikozes sīrups",
        "glikozes fruktozes sīrups",
        "fruktozes sīrups",
        "invertcukura sīrups",
        "kukurūzas sīrups",
        "medus",
        "melase",
        "karameļu sīrups",
    ),
    "carbohydrate": (
        "kviešu milti",
        "milti",
        "ciete",
        "kartupeļu ciete",
        "kukurūzas ciete",
        "rīsi",
        "rīsu milti",
        "auzas",
        "auzu pārslas",
        "kvieši",
        "mieži",
        "rudzi",
        "graudaugi",
        "maltodekstrīns",
    ),
    "fruit": (
        "augļi",
        "augļu",
        "ogas",
        "ogu",
        "augļu biezenis",
        "augļu sula",
        "āboli",
        "ābolu",
        "banāni",
        "banānu",
        "zemenes",
        "zemeņu",
        "avenes",
        "aveņu",
        "mellenes",
        "melleņu",
        "vīnogas",
        "vīnogu",
        "dateles",
        "dateļu",
        "rozīnes",
        "rozīņu",
        "žāvēti augļi",
        "dzērvenes",
        "dzērveņu",
    ),
    "salt": (
        "sāls",
        "sāls",
        "pārtikas sāls",
        "jūras sāls",
        "akmens sāls",
        "jodētais sāls",
        "nātrija hlorīds",
    ),
    "salty": (
        "sojas mērce",
        "sālījums",
        "sālīts siers",
        "sālīta",
        "sālīts",
        "sālītas",
        "kūpināta gaļa",
        "kūpināts",
        "sālīta zivs",
        "marinēts",
        "marinēti",
        "marinētas",
    ),
    "protein": (
        "gaļa",
        "liellopu",
        "liellops",
        "cūkgaļa",
        "vista",
        "vistas",
        "tītars",
        "tītara",
        "zivs",
        "zivis",
        "tuncis",
        "tuncis",
        "lasis",
        "ola",
        "olas",
        "olu",
        "olu baltums",
        "piena olbaltumvielas",
        "sūkalu olbaltumvielas",
        "sojas olbaltumvielas",
        "zirņu olbaltumvielas",
        "olbaltumvielu",
        "pākšaugi",
        "pupas",
        "lēcas",
    ),
    "nuts_seeds": (
        "mandeles",
        "mandeļu",
        "zemesrieksti",
        "zemesriekstu",
        "lazdu rieksti",
        "lazdu riekstu",
        "valrieksti",
        "valriekstu",
        "indijas rieksti",
        "indijas riekstu",
        "pistācijas",
        "pistāciju",
        "saulespuķu sēklas",
        "ķirbju sēklas",
        "sezama sēklas",
        "čia sēklas",
        "linsēklas",
        "rieksti",
        "riekstu",
    ),
    "cocoa": (
        "kakao",
        "kakao pulveris",
        "kakao masa",
        "kakao sviests",
        "šokolāde",
        "šokolādes",
    ),
}

LOW_FAT_DAIRY_TERMS = (
    "vājpiens",
    "vājpiena",
    "liespiens",
    "beztauku piens",
)

ADVISORY_MARKERS = (
    "var saturēt",
    "var saturēt pēdas",
    "var ietvert",
    "may contain",
)


@dataclass(frozen=True)
class IngredientEvidence:
    """A normalized ingredient mapping and its confidence metadata."""

    name: str
    normalized_name: str
    weak: bool = False
    percentage: float | None = None


def normalize_ingredient_text(value: Any) -> str:
    """Normalize Unicode, Latvian casing, punctuation, and whitespace."""
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value)).casefold()
    text = text.replace("-", " ")
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def _percentage(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        pass
    match = re.search(r"(\d+(?:[.,]\d+)?)\s*%", str(value))
    if not match:
        return None
    return float(match.group(1).replace(",", "."))


def _is_advisory(text: str) -> bool:
    normalized = normalize_ingredient_text(text)
    if any(marker in normalized for marker in ADVISORY_MARKERS):
        return True
    # The existing Latvian labels sometimes use "satur pienu" inside an
    # allergen statement.  It is not a definite ingredient declaration.
    return bool(re.search(r"\bsatur(?:u|ēt)?\s+(?:pien|soj|riekst)", normalized))


def normalize_ingredients(
    ingredients: Iterable[str | Mapping[str, Any]] | None,
    *,
    small_quantity_percent: float = 1.0,
) -> list[IngredientEvidence]:
    """
    Convert existing mapping rows or strings into evidence.

    Mapping rows may contain ingredient/name/clean_name, percentage, or weak
    flags.  Strings are supported for unit tests and future callers.
    """
    result: list[IngredientEvidence] = []
    seen: set[tuple[str, bool, float | None]] = set()
    for item in ingredients or ():
        if isinstance(item, Mapping):
            raw = (
                item.get("ingredient")
                or item.get("ingredient_name")
                or item.get("name")
                or item.get("clean_name")
                or ""
            )
            explicit_weak = bool(item.get("weak") or item.get("is_weak"))
            percent = _percentage(item.get("percentage"))
            if percent is None:
                percent = _percentage(raw)
        else:
            raw = item
            explicit_weak = False
            percent = _percentage(raw)

        name = str(raw).strip()
        normalized = normalize_ingredient_text(name)
        if not normalized:
            continue
        weak = (
            explicit_weak
            or _is_advisory(name)
            or (percent is not None and percent < small_quantity_percent)
        )
        key = (normalized, weak, percent)
        if key in seen:
            continue
        seen.add(key)
        result.append(IngredientEvidence(name, normalized, weak, percent))
    return result


def enrich_mapped_ingredients(
    ingredients: Iterable[str | Mapping[str, Any]] | None,
    raw_ingredients_text: str | None,
) -> list[str | dict[str, Any]]:
    """
    Add explicit quantity/advisory metadata to existing parsed mappings.

    Ingredient mappings remain the source of ingredient identity.  Raw text is
    used only to recover confidence metadata that the current parser discards.
    If a mapping cannot be located reliably, it is returned unchanged.
    """
    items: list[str | dict[str, Any]] = []
    raw_text = unicodedata.normalize(
        "NFKC",
        raw_ingredients_text or "",
    ).casefold()
    advisory_matches = list(re.finditer(
        r"\b(?:var\s+saturēt|var\s+ietvert|may\s+contain)\b([^.]*)",
        raw_text,
        flags=re.UNICODE,
    ))
    advisory_sections = [
        normalize_ingredient_text(match.group(0))
        for match in advisory_matches
    ]
    definite_characters = list(raw_text)
    for match in advisory_matches:
        definite_characters[match.start():match.end()] = " " * (
            match.end() - match.start()
        )
    definite_text = normalize_ingredient_text("".join(definite_characters))

    for item in ingredients or ():
        if isinstance(item, Mapping):
            enriched = dict(item)
            name = str(
                enriched.get("ingredient")
                or enriched.get("ingredient_name")
                or enriched.get("name")
                or ""
            )
        else:
            enriched = {"ingredient": item}
            name = str(item)

        normalized_name = normalize_ingredient_text(name)
        if normalized_name and advisory_sections:
            present_as_definite = _contains_term(
                definite_text,
                normalized_name,
            )
            advisory_match = any(
                _contains_term(section, normalized_name)
                for section in advisory_sections
            )
            if advisory_match and not present_as_definite:
                enriched["weak"] = True

        if raw_text and enriched.get("percentage") is None and normalized_name:
            words = normalized_name.split()
            phrase_pattern = (
                r"(?<!\w)"
                + r"[\W_]+".join(re.escape(word) for word in words)
                + r"(?!\w)"
            )
            for match in re.finditer(phrase_pattern, raw_text, flags=re.UNICODE):
                trailing = raw_text[match.end():match.end() + 30]
                percent_match = re.match(
                    r"\s*[\(\[]?\s*(\d+(?:[.,]\d+)?)\s*%",
                    trailing,
                )
                if percent_match:
                    enriched["percentage"] = float(
                        percent_match.group(1).replace(",", ".")
                    )
                    break
        items.append(enriched)
    return items


def _contains_term(text: str, term: str) -> bool:
    normalized_term = normalize_ingredient_text(term)
    if not normalized_term:
        return False
    pattern = r"(?<!\w)" + re.escape(normalized_term).replace(r"\ ", r"\s+") + r"(?!\w)"
    return re.search(pattern, text, flags=re.UNICODE) is not None


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _zero(value: Any) -> bool:
    number = _as_float(value)
    return number is not None and number <= 0


def _format_value(value: Any) -> float | int | None:
    number = _as_float(value)
    if number is None:
        return None
    return int(number) if number.is_integer() else round(number, 4)


class NutritionValidator:
    """Evaluate parsed ingredient mappings against one nutrition row."""

    def __init__(self, config: Mapping[str, Any] | None = None):
        merged = {
            "weights": dict(NUTRITION_VALIDATION_CONFIG["weights"]),
            "thresholds": dict(NUTRITION_VALIDATION_CONFIG["thresholds"]),
        }
        if config:
            for section in ("weights", "thresholds"):
                if section in config:
                    merged[section].update(config[section])
        self.config = merged

    @property
    def weights(self) -> Mapping[str, float]:
        return self.config["weights"]

    @property
    def thresholds(self) -> Mapping[str, float]:
        return self.config["thresholds"]

    def _matches(
        self,
        evidence: Sequence[IngredientEvidence],
        group: str,
    ) -> list[IngredientEvidence]:
        terms = INGREDIENT_KEYWORDS[group]
        matches = [
            item
            for item in evidence
            if any(_contains_term(item.normalized_name, term) for term in terms)
        ]
        # Advisory statements and explicitly tiny ingredients are intentionally
        # not enough to trigger a contradiction.
        return [item for item in matches if not item.weak]

    @staticmethod
    def _names(evidence: Sequence[IngredientEvidence]) -> list[str]:
        names: list[str] = []
        seen: set[str] = set()
        for item in evidence:
            if item.name not in seen:
                seen.add(item.name)
                names.append(item.name)
        return names

    def _finding(
        self,
        *,
        rule: str,
        severity: str,
        weight: str,
        evidence: Sequence[IngredientEvidence] = (),
        nutrition_field: str | list[str] | None = None,
        nutrition_value: Any = None,
        message: str,
        **extra: Any,
    ) -> dict[str, Any]:
        finding: dict[str, Any] = {
            "rule": rule,
            "severity": severity,
            "score": self.weights[weight],
            "ingredient_evidence": self._names(evidence),
            "nutrition_field": nutrition_field,
            "nutrition_value": _format_value(nutrition_value),
            "message": message,
        }
        for key, value in extra.items():
            if value is not None:
                finding[key] = value
        return finding

    def validate(
        self,
        ingredients: Iterable[str | Mapping[str, Any]] | None,
        nutrition: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        """Return a reproducible validation result for a product."""
        nutrition = nutrition or {}
        evidence = normalize_ingredients(
            ingredients,
            small_quantity_percent=float(
                self.thresholds["small_quantity_percent"]
            ),
        )
        reasons: list[dict[str, Any]] = []

        dairy = self._matches(evidence, "dairy")
        dairy = [
            item
            for item in dairy
            if not any(_contains_term(item.normalized_name, term) for term in LOW_FAT_DAIRY_TERMS)
        ]
        fat = self._matches(evidence, "fat")
        fat_rich = self._matches(evidence, "fat_rich")
        sugar = self._matches(evidence, "sugar")
        carbohydrate = self._matches(evidence, "carbohydrate")
        fruit = self._matches(evidence, "fruit")
        salt = self._matches(evidence, "salt")
        salty = self._matches(evidence, "salty")
        protein = self._matches(evidence, "protein")
        nuts_seeds = self._matches(evidence, "nuts_seeds")
        cocoa = self._matches(evidence, "cocoa")

        fat_total = nutrition.get("fat_total")
        fat_saturated = nutrition.get("fat_saturated")
        carbs_total = nutrition.get("carbs_total")
        carbs_sugars = nutrition.get("carbs_sugars")
        protein_value = nutrition.get("protein")
        salt_value = nutrition.get("salt")

        if dairy and _zero(fat_saturated):
            reasons.append(self._finding(
                rule="milk_present_but_saturated_fat_zero",
                severity="high",
                weight="dairy_saturated_fat_zero",
                evidence=dairy,
                nutrition_field="saturated_fat",
                nutrition_value=fat_saturated,
                message="Dairy ingredients are present but saturated fat is reported as zero.",
            ))

        if fat and _zero(fat_total):
            reasons.append(self._finding(
                rule="fat_ingredient_present_but_fat_zero",
                severity="high",
                weight="fat_ingredient_zero",
                evidence=fat,
                nutrition_field="fat",
                nutrition_value=fat_total,
                message="A fat or oil ingredient is present but total fat is reported as zero.",
            ))

        if fat_rich and _zero(fat_saturated):
            reasons.append(self._finding(
                rule="high_saturated_fat_ingredient_but_saturated_fat_zero",
                severity="medium",
                weight="strong_association_low",
                evidence=fat_rich,
                nutrition_field="saturated_fat",
                nutrition_value=fat_saturated,
                message="A strongly saturated-fat-associated ingredient is present but saturated fat is reported as zero.",
            ))

        if sugar and _zero(carbs_sugars):
            reasons.append(self._finding(
                rule="sugar_ingredient_present_but_sugars_zero",
                severity="high",
                weight="sugar_ingredient_zero",
                evidence=sugar,
                nutrition_field="sugars",
                nutrition_value=carbs_sugars,
                message="A sugar ingredient is present but sugars are reported as zero.",
            ))

        if carbohydrate and _zero(carbs_total):
            reasons.append(self._finding(
                rule="carbohydrate_ingredient_present_but_carbohydrates_zero",
                severity="medium",
                weight="strong_association_low",
                evidence=carbohydrate,
                nutrition_field="carbohydrates",
                nutrition_value=carbs_total,
                message="A carbohydrate ingredient is present but carbohydrates are reported as zero.",
            ))

        if fruit and _zero(carbs_sugars):
            reasons.append(self._finding(
                rule="fruit_present_but_sugars_zero",
                severity="low",
                weight="weak_association",
                evidence=fruit,
                nutrition_field="sugars",
                nutrition_value=carbs_sugars,
                message="Fruit ingredients are present but sugars are reported as zero.",
            ))

        if salt and _zero(salt_value):
            reasons.append(self._finding(
                rule="salt_present_but_salt_zero",
                severity="high",
                weight="salt_ingredient_zero",
                evidence=salt,
                nutrition_field="salt",
                nutrition_value=salt_value,
                message="Salt is present in the ingredients but salt is reported as zero.",
            ))

        if salty and (
            _as_float(salt_value) is not None
            and _as_float(salt_value) <= float(self.thresholds["low_salt_grams"])
        ):
            reasons.append(self._finding(
                rule="salty_ingredient_but_low_salt",
                severity="medium",
                weight="salty_ingredient_low_salt",
                evidence=salty,
                nutrition_field="salt",
                nutrition_value=salt_value,
                message="A salty ingredient is present but reported salt is unusually low.",
            ))

        if protein and _zero(protein_value):
            reasons.append(self._finding(
                rule="protein_ingredient_present_but_protein_zero",
                severity="high",
                weight="protein_ingredient_zero",
                evidence=protein,
                nutrition_field="protein",
                nutrition_value=protein_value,
                message="A protein-rich ingredient is present but protein is reported as zero.",
            ))

        if nuts_seeds and _zero(fat_total):
            reasons.append(self._finding(
                rule="nuts_or_seeds_present_but_fat_zero",
                severity="low",
                weight="weak_association",
                evidence=nuts_seeds,
                nutrition_field="fat",
                nutrition_value=fat_total,
                message="Nuts or seeds are present but total fat is reported as zero.",
            ))

        if cocoa:
            if _zero(fat_total):
                reasons.append(self._finding(
                    rule="cocoa_or_chocolate_but_fat_zero",
                    severity="low",
                    weight="weak_association",
                    evidence=cocoa,
                    nutrition_field="fat",
                    nutrition_value=fat_total,
                    message="Cocoa or chocolate is present but total fat is reported as zero.",
                ))
            if _zero(fat_saturated):
                reasons.append(self._finding(
                    rule="cocoa_or_chocolate_but_saturated_fat_zero",
                    severity="low",
                    weight="weak_association",
                    evidence=cocoa,
                    nutrition_field="saturated_fat",
                    nutrition_value=fat_saturated,
                    message="Cocoa or chocolate is present but saturated fat is reported as zero.",
                ))
            if _zero(carbs_sugars):
                reasons.append(self._finding(
                    rule="cocoa_or_chocolate_but_sugars_zero",
                    severity="low",
                    weight="weak_association",
                    evidence=cocoa,
                    nutrition_field="sugars",
                    nutrition_value=carbs_sugars,
                    message="Cocoa or chocolate is present but sugars are reported as zero.",
                ))

        if (
            _as_float(fat_saturated) is not None
            and _as_float(fat_total) is not None
            and _as_float(fat_saturated) > _as_float(fat_total)
        ):
            reasons.append(self._finding(
                rule="saturated_fat_exceeds_total_fat",
                severity="high",
                weight="impossible_relationship",
                nutrition_field="saturated_fat",
                nutrition_value=fat_saturated,
                related_nutrition_field="fat",
                related_nutrition_value=_format_value(fat_total),
                message="Saturated fat cannot exceed total fat.",
            ))

        if (
            _as_float(carbs_sugars) is not None
            and _as_float(carbs_total) is not None
            and _as_float(carbs_sugars) > _as_float(carbs_total)
        ):
            reasons.append(self._finding(
                rule="sugars_exceed_carbohydrates",
                severity="high",
                weight="impossible_relationship",
                nutrition_field="sugars",
                nutrition_value=carbs_sugars,
                related_nutrition_field="carbohydrates",
                related_nutrition_value=_format_value(carbs_total),
                message="Sugars cannot exceed total carbohydrates.",
            ))

        energy_declared = _as_float(nutrition.get("energy_kcal"))
        if energy_declared is None:
            energy_kj = _as_float(nutrition.get("energy_kj"))
            if energy_kj is not None:
                energy_declared = energy_kj / 4.184
        protein_number = _as_float(protein_value)
        carbs_number = _as_float(carbs_total)
        fat_number = _as_float(fat_total)
        fiber_number = _as_float(nutrition.get("fiber")) or 0.0
        if (
            energy_declared is not None
            and energy_declared > 0
            and protein_number is not None
            and carbs_number is not None
            and fat_number is not None
        ):
            estimated_kcal = (
                protein_number * 4
                + carbs_number * 4
                + fat_number * 9
                + fiber_number * 2
            )
            absolute_difference = abs(energy_declared - estimated_kcal)
            relative_difference = absolute_difference / energy_declared
            if (
                relative_difference > float(self.thresholds["energy_relative_difference"])
                and absolute_difference
                > float(self.thresholds["energy_absolute_difference_kcal"])
            ):
                reasons.append(self._finding(
                    rule="energy_inconsistent_with_macronutrients",
                    severity="medium",
                    weight="energy_inconsistent",
                    nutrition_field="energy_kcal",
                    nutrition_value=energy_declared,
                    estimated_energy_kcal=round(estimated_kcal, 2),
                    relative_difference=round(relative_difference, 4),
                    message="Declared energy differs substantially from the macronutrient estimate.",
                ))

        cluster_pairs = (
            ("fat", fat or fat_rich or nuts_seeds or cocoa, fat_total),
            ("saturated_fat", dairy or fat_rich, fat_saturated),
            ("sugars", sugar or fruit or cocoa, carbs_sugars),
            ("carbohydrates", carbohydrate, carbs_total),
            ("protein", protein, protein_value),
            ("salt", salt or salty, salt_value),
        )
        cluster_fields = [
            field for field, matched, value in cluster_pairs if matched and _zero(value)
        ]
        if len(cluster_fields) >= int(self.thresholds["zero_cluster_min_fields"]):
            cluster_evidence: list[IngredientEvidence] = []
            for _, matched, _ in cluster_pairs:
                for item in matched:
                    if item not in cluster_evidence:
                        cluster_evidence.append(item)
            reasons.append(self._finding(
                rule="multiple_nutrition_values_inconsistent_with_ingredients",
                severity="medium",
                weight="zero_value_cluster",
                evidence=cluster_evidence,
                nutrition_field=cluster_fields,
                nutrition_value=0,
                message="Several nutritionally meaningful ingredient groups correspond to zero nutrition values.",
            ))

        score_number = float(sum(float(reason["score"]) for reason in reasons))
        score = (
            int(score_number)
            if score_number.is_integer()
            else round(score_number, 2)
        )
        thresholds = self.thresholds
        if score <= float(thresholds["none_max"]):
            level = "none"
        elif score <= float(thresholds["low_max"]):
            level = "low"
        elif score <= float(thresholds["medium_max"]):
            level = "medium"
        else:
            level = "high"
        return {
            "suspicion_level": level,
            "suspicion_score": score,
            "reasons": reasons,
        }


def summarize_validation_results(results: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Create database-independent summary counters for a backfill run."""
    levels = {"none": 0, "low": 0, "medium": 0, "high": 0}
    rule_counts: dict[str, int] = {}
    total = 0
    for result in results:
        total += 1
        level = result.get("suspicion_level", "none")
        levels[level] = levels.get(level, 0) + 1
        for reason in result.get("reasons", []) or []:
            rule = reason.get("rule")
            if rule:
                rule_counts[rule] = rule_counts.get(rule, 0) + 1
    rule_percentages = {
        rule: round(count * 100 / total, 2) if total else 0.0
        for rule, count in sorted(rule_counts.items(), key=lambda item: (-item[1], item[0]))
    }
    return {
        "products_checked": total,
        "levels": levels,
        "rule_counts": dict(sorted(rule_counts.items(), key=lambda item: (-item[1], item[0]))),
        "rule_percentages": rule_percentages,
    }