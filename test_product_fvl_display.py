"""Read-only product detail display regressions, without a database connection."""

from decimal import Decimal
from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest


@pytest.mark.parametrize(
    "percentage, category_type, expected, source",
    [
        (Decimal("83.25"), "general", "83.25%", "manuāli ievadīts"),
        (Decimal("0.00"), "full_fvn", "0%", "manuāli ievadīts"),
        (None, "full_fvn", "100%", "kategorijas noklusējums"),
        (None, "half_fvn", "50%", "kategorijas noklusējums"),
        (None, "general", "0%", "kategorijas noklusējums"),
    ],
)
def test_fvl_share_in_product_details(monkeypatch, percentage, category_type, expected, source):
    import main

    product = dict(
        product_id=1, name="Test product", sku="",
        energy_kj=198, fat_total=0, carbs_total=11.3,
        protein=0, salt=0, fiber=0,
        fruit_veg_legume_percent=percentage,
        nutriscore_category_type=category_type,
    )
    monkeypatch.setattr(main, "ProductViewDatabase", lambda: SimpleNamespace(
        get_product_details=lambda _: product, close=lambda: None,
    ))
    monkeypatch.setattr(main, "render_nutrition_edit_form", lambda *_: None)
    monkeypatch.setattr(main, "render_nova_edit_form", lambda *_: None)
    app = AppTest.from_string(
        "import streamlit as st\n"
        "from main import render_product_detail_view\n"
        "st.session_state.selected_product_id = 1\n"
        "render_product_detail_view()\n"
    ).run()

    assert not app.exception
    assert not app.error
    metrics = list(app.metric)
    assert [metric.label for metric in metrics] == [
        "Enerģija", "Tauki", "Ogļhidrāti", "Olbaltumvielas", "Sāls",
        "Šķiedrvielas", "Augļi, dārzeņi un pākšaugi",
    ]
    assert metrics[-1].value == expected
    assert [caption.value for caption in app.caption].count(f"Avots: {source}") == 1
    assert not any("Augļi, dārzeņi un pākšaugi:" in c.value for c in app.caption)
    # The single summary follows nutrition metrics and precedes the editor.
    elements = list(app)
    fvl_index = next(i for i, el in enumerate(elements) if el is metrics[-1])
    editor_index = next(
        i for i, el in enumerate(elements)
        if el.type == "expander" and "Rediģēt uzturvielu" in el.label
    )
    assert fvl_index < editor_index
