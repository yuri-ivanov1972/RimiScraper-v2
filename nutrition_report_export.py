"""Formatting helpers for nutrition validation report exports."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


SUSPICIOUS_PRODUCT_ELIGIBILITY_SQL = """
    COALESCE((
        SELECT pph.is_available
        FROM product_price_history pph
        WHERE pph.product_id = nvr.product_id
        ORDER BY pph.recorded_at DESC, pph.price_history_id DESC
        LIMIT 1
    ), FALSE) IS TRUE
    AND COALESCE((
        SELECT ppl.status
        FROM product_processing_log ppl
        JOIN category_processing_jobs cpj ON cpj.id = ppl.job_id
        WHERE ppl.product_id = nvr.product_id
          AND cpj.job_type = 'suspicious_refresh'
        ORDER BY cpj.id DESC, ppl.id DESC
        LIMIT 1
    ), '') <> 'failed'
"""


def _display_value(value: Any) -> str:
    if value is None or value == "":
        return "missing"
    if isinstance(value, (list, tuple)):
        return ", ".join(str(item) for item in value) or "missing"
    return str(value)


def format_findings_for_csv(reasons: Iterable[Any] | None) -> str:
    """Combine all findings into numbered, readable blocks for one CSV cell."""
    formatted: list[str] = []
    for index, reason in enumerate(reasons or (), start=1):
        if isinstance(reason, Mapping):
            evidence = reason.get("ingredient_evidence")
            if isinstance(evidence, (list, tuple)):
                evidence = ", ".join(str(item) for item in evidence)
            fields = [
                f"{index}. {_display_value(reason.get('message'))}",
                f"Rule: {_display_value(reason.get('rule'))}",
                f"Severity: {_display_value(reason.get('severity'))}",
                f"Reason score: {_display_value(reason.get('score'))}",
                f"Ingredient evidence: {_display_value(evidence)}",
                (
                    "Nutrition: "
                    f"{_display_value(reason.get('nutrition_field'))}="
                    f"{_display_value(reason.get('nutrition_value'))}"
                ),
            ]
        else:
            fields = [
                f"{index}. {_display_value(reason)}",
                "Rule: missing",
                "Severity: missing",
                "Reason score: missing",
                "Ingredient evidence: missing",
                "Nutrition: missing=missing",
            ]
        formatted.append(" | ".join(fields))
    return "\n".join(formatted)