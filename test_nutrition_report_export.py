"""Tests for suspicious-product CSV finding details."""

import csv
import io

from nutrition_report_export import format_findings_for_csv


def test_formats_one_complete_finding():
    result = format_findings_for_csv([{
        "message": "Sugar is present, but sugars are unreported.",
        "rule": "sugar_ingredient_present_but_sugars_zero",
        "severity": "high",
        "score": 8,
        "ingredient_evidence": ["cukurs", "medus"],
        "nutrition_field": "sugars",
        "nutrition_value": 0,
    }])

    assert result == (
        "1. Sugar is present, but sugars are unreported. | "
        "Rule: sugar_ingredient_present_but_sugars_zero | Severity: high | "
        "Reason score: 8 | Ingredient evidence: cukurs, medus | "
        "Nutrition: sugars=0"
    )


def test_formats_multiple_findings_on_separate_numbered_lines():
    result = format_findings_for_csv([
        {"message": "Sugar missing", "rule": "sugar_rule"},
        {"message": "Salt missing", "rule": "salt_rule"},
    ])

    lines = result.splitlines()
    assert len(lines) == 2
    assert lines[0].startswith("1. Sugar missing")
    assert lines[1].startswith("2. Salt missing")
    assert "Rule: salt_rule" in lines[1]


def test_handles_partial_and_legacy_findings_with_clear_missing_values():
    result = format_findings_for_csv([
        {"message": "Partial finding", "nutrition_value": None},
        "Legacy finding",
    ])

    assert "Rule: missing" in result
    assert "Nutrition: missing=missing" in result
    assert "2. Legacy finding" in result


def test_multiline_findings_remain_valid_in_csv_cell():
    findings = format_findings_for_csv([
        {"message": "Contains sugar, syrup", "rule": "sugar_rule"},
        {"message": "Contains salt", "rule": "salt_rule"},
    ])
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["SKU", "Finding details"])
    writer.writeheader()
    writer.writerow({"SKU": "123", "Finding details": findings})

    parsed = list(csv.DictReader(io.StringIO(output.getvalue())))
    assert parsed == [{"SKU": "123", "Finding details": findings}]