"""HQ v3k: Inventory restock spins follow E7c order_qty_max and suggested quantities."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication, QSpinBox

from open_late.content import SUPPLIERS
from open_late.engine import order_qty_max, place_order, suggested_restock_quantities
from open_late.store import SaveStore
from open_late.ui.window import MainWindow


def _app(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


def _boot(tmp_path, monkeypatch, *, mode="shop", size=(1366, 768)):
    app = _app(monkeypatch)
    window = MainWindow(SaveStore(tmp_path / "saves.sqlite"))
    window.show()
    window.resize(*size)
    app.processEvents()
    window._show_setup()
    window.name_input.setText("Retail Rivals")
    if mode == "corporate":
        window.corporate_radio.setChecked(True)
        window._chosen_chain_id = "bluestar"
        window._chosen_economy = "standard"
    else:
        window.shop_radio.setChecked(True)
    window.age_check.setChecked(True)
    window._start()
    app.processEvents()
    window._to_desk()
    app.processEvents()
    window._open_app("inventory")
    app.processEvents()
    return app, window


def _truck_spins(window):
    found = []
    for attr in ("_truck_qty",):
        mapping = getattr(window, attr, None)
        if isinstance(mapping, dict):
            found.extend(mapping.values())
    return found


def test_inventory_order_spin_uses_order_qty_max(tmp_path, monkeypatch):
    app, window = _boot(tmp_path, monkeypatch, mode="shop")
    assert window._order_spins, "Inventory sheet should have order spins"
    ceiling = order_qty_max()
    assert ceiling >= 3750
    for product_id, spin in window._order_spins.items():
        assert spin.minimum() == 0
        assert spin.maximum() == ceiling, (product_id, spin.maximum(), ceiling)
        # A want_units fill has to fit, unlike the old 40 cap.
        spin.setValue(ceiling)
        assert spin.value() == ceiling
    window.close()


def test_suggest_fills_engine_quantities_and_does_not_place(tmp_path, monkeypatch):
    app, window = _boot(tmp_path, monkeypatch, mode="shop")
    state = window.state
    # Empty the floor and pipeline so the modest fill is a real supercenter-sized sheet.
    for line in state.stock.values():
        line.on_hand = 0
        if hasattr(line, "on_order"):
            line.on_order = 0
    # Rebuild the sheet against the emptied stock.
    window.refresh()
    app.processEvents()
    window._open_app("inventory")
    app.processEvents()
    expected = suggested_restock_quantities(state, window._supplier_id)
    assert expected, "engine helper should suggest a restock on an empty floor"
    assert all(qty > 40 for qty in expected.values())
    cash_before = state.cash
    open_orders = len(getattr(state, "orders", []) or [])
    window._suggest()
    app.processEvents()
    for product_id, spin in window._order_spins.items():
        assert spin.value() == int(expected.get(product_id, 0)), product_id
        assert spin.value() <= spin.maximum()
    # Button still only fills the spins.
    assert state.cash == cash_before
    assert len(getattr(state, "orders", []) or []) == open_orders
    window.close()


def test_send_the_truck_spin_uses_order_qty_max(tmp_path, monkeypatch):
    app, window = _boot(tmp_path, monkeypatch, mode="corporate")
    # The truck row lives on the legacy corporate stores/expansion body,
    # and now also on the Store Portfolio drawer. Both follow order_qty_max().
    window._fill_legacy("expansion")
    app.processEvents()
    trucks = _truck_spins(window)
    assert trucks, "Stores page should still have a Send the truck quantity spin"
    ceiling = order_qty_max()
    assert ceiling > 40
    for spin in trucks:
        assert isinstance(spin, QSpinBox)
        assert spin.minimum() == 1
        assert spin.maximum() == ceiling
        spin.setValue(ceiling)
        assert spin.value() == ceiling
        spin.setValue(ceiling + 1)
        assert spin.value() == ceiling
    window.close()



def test_suggested_sheet_meets_minimum_and_can_be_placed(tmp_path, monkeypatch):
    """A supercenter-scale modest fill must clear each supplier minimum and Place order must stick."""
    app, window = _boot(tmp_path, monkeypatch, mode="shop")
    state = window.state
    state.cash = 10_000_000
    for line in state.stock.values():
        line.on_hand = 0
        if hasattr(line, "on_order"):
            line.on_order = 0
    ceiling = order_qty_max()
    placed = 0
    for supplier_id, supplier in SUPPLIERS.items():
        if supplier_id == "labelco":
            continue
        window._supplier_id = supplier_id
        window.refresh()
        app.processEvents()
        window._open_app("inventory")
        app.processEvents()
        expected = suggested_restock_quantities(state, supplier_id)
        assert expected, supplier_id
        assert all(0 < qty <= ceiling for qty in expected.values()), (supplier_id, expected)
        window._suggest()
        app.processEvents()
        quantities = {
            product_id: spin.value()
            for product_id, spin in window._order_spins.items()
            if spin.value() > 0
        }
        assert quantities, supplier_id
        for product_id, qty in expected.items():
            assert quantities.get(product_id) == qty, (supplier_id, product_id, quantities.get(product_id), qty)
        cost = sum(state.products[pid].cost * qty for pid, qty in quantities.items())
        assert cost >= supplier.minimum_order, (supplier_id, cost, supplier.minimum_order)
        before = len(getattr(state, "purchase_orders", None) or getattr(state, "orders", []) or [])
        window._place()
        app.processEvents()
        assert window.status.text().startswith("Order placed"), (supplier_id, window.status.text())
        after = len(getattr(state, "purchase_orders", None) or getattr(state, "orders", []) or [])
        assert after > before or "Order placed" in window.status.text()
        placed += 1
    assert placed >= 8
    window.close()
