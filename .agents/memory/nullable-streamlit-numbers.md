---
name: Nullable Streamlit numbers
description: Why optional numbers need a stable nullable default even when reopening saved values.
---

Keep optional Streamlit numeric widgets nullable across reruns and fresh sessions, including when reopening a saved number.

**Why:** In Streamlit 1.41.1, a number input initialized with a numeric default can deserialize an emptied input back to that default instead of None. Saving appears successful but does not clear the override. The issue also appears in AppTest.

**How to apply:** Seed saved values through session state before widget creation and retain `value=None` as the widget default. Test clearing after reopening a nonempty saved value, not only clearing an input initially rendered empty. Never combine an editable override with a separate checked fallback control that silently discards its contents.
