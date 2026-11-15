"""Patch E7c: every core department still sells after a 4-week standard run."""

from __future__ import annotations

from open_late.content import SUPPLIERS, want_units
from open_late.departments import DEPARTMENT_IDS, department_sales
from open_late.engine import (
    new_game,
    order_qty_max,
    place_order,
    suggested_restock_quantities,
)
from open_late.hq import HOME_STORE_ID
from tests.test_e6_yupper import play


def test_suggested_restock_clears_supplier_minimums():
    qty_max = order_qty_max()
    assert qty_max >= want_units("grocery")
    for supplier_id, supplier in SUPPLIERS.items():
        if supplier_id == "labelco":
            continue
        state = new_game("Prairie Wire", "shop", seed=22, economy_difficulty="standard")
        for line in state.stock.values():
            line.on_hand = 0
            line.on_order = 0
        state.cash = 10_000_000
        quantities = suggested_restock_quantities(state, supplier_id)
        assert quantities, supplier_id
        assert all(0 < qty <= qty_max for qty in quantities.values()), supplier_id
        cost = sum(state.products[pid].cost * qty for pid, qty in quantities.items())
        assert cost >= supplier.minimum_order, (supplier_id, cost, supplier.minimum_order)
        text = place_order(state, supplier_id, quantities)
        assert text.startswith("Order placed"), (supplier_id, text)


def test_core_departments_sell_over_four_standard_weeks():
    state = new_game("Prairie Wire", "shop", seed=22, economy_difficulty="standard")
    result = play(state, 4)
    assert not result["failed"], result["reason"]
    whole = department_sales(state, HOME_STORE_ID, days=28)
    last = department_sales(state, HOME_STORE_ID, days=8)
    missing_whole = [dept for dept in DEPARTMENT_IDS if whole.get(dept, 0) <= 0]
    missing_last = [dept for dept in DEPARTMENT_IDS if last.get(dept, 0) <= 0]
    assert not missing_whole, (missing_whole, whole)
    assert not missing_last, (missing_last, last)
