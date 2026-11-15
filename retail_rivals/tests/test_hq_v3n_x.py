"""HQ v3n: Planogram SKU rail and Inventory paging for the E8 catalog."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QWidget,
)

from open_late.store import SaveStore
from open_late.ui.hq_product import ProductTile
from open_late.ui.window import MainWindow


def _app(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


def _boot(tmp_path, monkeypatch, *, mode="corporate", size=(1366, 768), chain="bluestar"):
    app = _app(monkeypatch)
    window = MainWindow(SaveStore(tmp_path / "saves.sqlite"))
    window.show()
    window.setMinimumSize(1, 1)
    window.resize(*size)
    app.processEvents()
    window._show_setup()
    window.name_input.setText("Retail Rivals")
    if mode == "corporate":
        window.corporate_radio.setChecked(True)
        window._chosen_chain_id = chain
    else:
        window.shop_radio.setChecked(True)
        window._chosen_chain_id = chain
    window._chosen_economy = "standard"
    window.age_check.setChecked(True)
    window._start()
    app.processEvents()
    window._to_desk()
    app.processEvents()
    window.resize(*size)
    app.processEvents()
    return app, window


def _text(widget) -> str:
    parts = []
    if isinstance(widget, (QLabel, QPushButton, QLineEdit)):
        parts.append(widget.text() if not isinstance(widget, QLineEdit) else widget.text())
    for child in widget.findChildren(QLabel) + widget.findChildren(QPushButton):
        parts.append(child.text())
    return "\n".join(parts)


def test_planogram_rail_shows_mixed_departments_and_pages_grocery(tmp_path, monkeypatch):
    app, window = _boot(tmp_path, monkeypatch, mode="corporate")
    window._open_app("planograms")
    app.processEvents()
    page = window.desktop.planogram
    text = _text(page)
    assert "Planogram Editor" in text
    assert page.findChildren(ProductTile)
    # Unfiltered rail mixes departments so grocery cannot hide the rest.
    assert "Bananas" in text or "banana" in text.lower()
    assert "Grocery" in text and "Produce" in text
    tiles = page.findChildren(ProductTile)
    assert 13 <= len(tiles) <= 80
    # Every department is in the filter, not just the first six.
    combo = page.findChild(QComboBox, "skuDeptFilter")
    assert combo is not None
    labels = [combo.itemText(i) for i in range(combo.count())]
    assert combo.count() >= 14
    assert "Toys" in labels and "Clothing" in labels and "Seasonal" in labels
    # Filtering grocery pages or scrolls the 24-48 family wall, without
    # squashing tiles into the viewport.
    page._set_dept("grocery")
    app.processEvents()
    grocery_text = _text(page)
    assert "flour" in grocery_text.lower()
    grocery_tiles = page.findChildren(ProductTile)
    assert grocery_tiles
    assert all(tile.height() >= 64 for tile in grocery_tiles)
    nxt = page.findChild(QPushButton, "skuRailNext")
    assert nxt is not None
    first_page = grocery_text
    if nxt.isEnabled():
        page._step_sku_page(1)
        app.processEvents()
        later = _text(page)
        assert later != first_page
        later_tiles = page.findChildren(ProductTile)
        assert later_tiles and all(tile.height() >= 64 for tile in later_tiles)
    else:
        # A single scrollable page may hold the whole department.
        scroll = page.findChild(QScrollArea, "skuRailScroll")
        assert scroll is not None
        assert len(page.findChildren(ProductTile)) >= 20
    window.close()


def test_inventory_search_filter_and_paging(tmp_path, monkeypatch):
    app, window = _boot(tmp_path, monkeypatch, mode="shop", chain="megamart")
    window._open_app("inventory")
    app.processEvents()
    search = window.findChild(QLineEdit, "inventorySearch")
    dept = window.findChild(QComboBox, "inventoryDept")
    scroll = window.findChild(QScrollArea, "inventoryScroll")
    assert search is not None and dept is not None and scroll is not None
    # Opening the sheet does not build a spin for every SKU at once.
    assert 1 <= len(window._order_spins) <= 18
    for spin in window._order_spins.values():
        assert spin.maximum() >= 40
    total_before = window.findChild(QLabel, "inventoryPage")
    assert total_before is not None
    assert "of" in total_before.text()
    nxt = window.findChild(QPushButton, "inventoryNext")
    assert nxt is not None and nxt.isEnabled()
    first_ids = set(window._order_spins)
    window._inv_step_page(1)
    app.processEvents()
    later_ids = set(window._order_spins)
    assert later_ids and later_ids != first_ids
    # Search narrows the list.
    window._inv_query = "flour"
    window._inv_page = 0
    window._reload_inventory()
    app.processEvents()
    text = _text(window.desktop)
    assert "flour" in text.lower()
    assert len(window._order_spins) <= 18
    window.close()


def test_inventory_suggest_fills_hidden_pages(tmp_path, monkeypatch):
    app, window = _boot(tmp_path, monkeypatch, mode="shop", chain="megamart")
    window._open_app("inventory")
    app.processEvents()
    state = window.state
    for line in state.stock.values():
        line.on_hand = 0
        if hasattr(line, "on_order"):
            line.on_order = 0
    window.refresh()
    app.processEvents()
    window._open_app("inventory")
    app.processEvents()
    from open_late.engine import suggested_restock_quantities
    expected = suggested_restock_quantities(state, window._supplier_id)
    assert expected
    window._suggest()
    app.processEvents()
    for product_id, spin in window._order_spins.items():
        assert spin.value() == int(expected.get(product_id, 0)), product_id
    # Suggestions for SKUs on later pages are kept.
    hidden = [pid for pid in expected if pid not in window._order_spins]
    if hidden:
        assert any(int(window._order_qtys.get(pid, 0)) == int(expected[pid]) for pid in hidden)
    window.close()
