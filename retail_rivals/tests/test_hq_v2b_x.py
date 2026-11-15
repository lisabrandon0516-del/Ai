"""HQ v2b: dark dashboard, state-border map, product tiles, last-8-weeks copy."""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QWidget

from open_late.store import SaveStore
from open_late.ui.hq_adapter import street_address
from open_late.ui.hq_art import StorefrontArt, StoreMap
from open_late.ui.hq_product import ProductTile
from open_late.ui.theme import DASH_BG
from open_late.ui.window import MainWindow


def _boot(tmp_path, monkeypatch, *, corporate: bool = True, name: str = "Retail Rivals", chain_id: str | None = "bluestar"):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    window = MainWindow(SaveStore(tmp_path / "saves.sqlite"))
    window.show()
    window.resize(1366, 768)
    app.processEvents()
    window._show_setup()
    window.name_input.setText(name)
    if corporate:
        window.corporate_radio.setChecked(True)
    else:
        window.shop_radio.setChecked(True)
    window.age_check.setChecked(True)
    if chain_id:
        window._chosen_chain_id = chain_id
    window._start()
    app.processEvents()
    return app, window


def _text(widget) -> str:
    parts = []
    if isinstance(widget, (QLabel, QPushButton)):
        parts.append(widget.text())
    for child in widget.findChildren(QLabel) + widget.findChildren(QPushButton):
        parts.append(child.text())
    return "\n".join(parts)


def _pixel(widget, x, y) -> str:
    image = widget.grab().toImage()
    x = min(max(0, int(x)), image.width() - 1)
    y = min(max(0, int(y)), image.height() - 1)
    return QColor(image.pixel(x, y)).name().lower()


def _is_navy(color: str) -> bool:
    """True for the dashboard navy (#09152D and close control fills)."""
    c = QColor(color)
    return c.red() < 40 and c.green() < 50 and c.blue() < 80 and c.blue() >= c.red() and c.blue() >= c.green()


def _is_light(color: str) -> bool:
    c = QColor(color)
    return c.red() > 180 and c.green() > 180 and c.blue() > 180


def test_dashboard_is_dark_with_three_sparkline_kpis(tmp_path, monkeypatch):
    app, window = _boot(tmp_path, monkeypatch)
    window._open_app("home")
    app.processEvents()
    home = window.desktop.home
    topbar = window.desktop.topbar
    body = window.desktop.body
    navy = {DASH_BG.lower(), "#09152d"}
    assert home.palette().color(QPalette.ColorRole.Window).name().lower() in navy
    assert topbar.palette().color(QPalette.ColorRole.Window).name().lower() in navy
    assert body.palette().color(QPalette.ColorRole.Window).name().lower() in navy
    # Gutters around the cards and the title band must be navy, not white.
    assert _is_navy(_pixel(home, 8, 8))
    assert _is_navy(_pixel(home, 12, 40))
    assert _is_navy(_pixel(topbar, topbar.width() // 2, 10))
    title = home.findChild(QLabel, "pageTitle")
    assert title is not None and title.text() == "Dashboard"
    assert title.font().pixelSize() >= 28
    text = _text(home)
    assert "TAKE" in text and "DRAWER" in text and "STORE P&L" in text and "SUNDAY" in text
    tiles = [home.findChild(QWidget, name) for name in ("kpiTake", "kpiContribution", "kpiDrawer")]
    assert all(tile is not None for tile in tiles)
    assert {tile.height() for tile in tiles} == {128}
    for tile in tiles:
        assert any(child.metaObject().className() == "Sparkline" for child in tile.findChildren(QWidget))
    assert home.findChild(QWidget, "marketingCard") is not None
    assert "Launch a campaign" in text
    assert home.findChild(StoreMap) is not None
    # Chrome is dark on this page and returns to light on portfolio and planogram.
    assert window.desktop.topbar.property("dashDark") in ("true", True)
    window._open_app("stores")
    app.processEvents()
    assert window.desktop.topbar.property("dashDark") in ("false", False, None)
    assert _is_light(_pixel(window.desktop.topbar, window.desktop.topbar.width() // 2, 10))
    window._open_app("planograms")
    app.processEvents()
    assert window.desktop.topbar.property("dashDark") in ("false", False, None)
    assert _is_light(_pixel(window.desktop.topbar, window.desktop.topbar.width() // 2, 10))
    window.close()


def test_portfolio_has_state_borders_street_address_and_last_8_wks(tmp_path, monkeypatch):
    app, window = _boot(tmp_path, monkeypatch)
    window._open_app("stores")
    app.processEvents()
    page = window.desktop.stores
    text = _text(page)
    assert "YTD" not in text
    assert "Last 8 wks" in text
    door = window.state.doors[0]
    address = street_address(door)
    assert door.city in address
    assert address in _text(page.drawer)
    # Fictional street has a number and is not only "City, ST".
    assert any(ch.isdigit() for ch in address)
    assert address != f"{door.city}, IN"
    assert page.findChildren(StorefrontArt)
    assert "Available to lease" in text or "markets available" in text.lower() or "Sign a lease" in text
    window.close()


def test_planogram_shelf_and_rail_use_product_tiles(tmp_path, monkeypatch):
    app, window = _boot(tmp_path, monkeypatch)
    window._open_app("planograms")
    app.processEvents()
    page = window.desktop.planogram
    text = _text(page)
    assert "Planogram Editor" in text
    assert page.findChildren(ProductTile)
    # Shelf is showing individual SKUs, not a department-sized icon grid.
    assert any(name in text for name in ("Flour", "Bananas", "Milk", "Tee", "Hoodie", "Shampoo", "Puzzle"))
    window.close()


def test_street_address_is_deterministic(tmp_path, monkeypatch):
    app, window = _boot(tmp_path, monkeypatch)
    door = window.state.doors[0]
    assert street_address(door) == street_address(door)
    window.close()


def test_new_game_uses_standard_economy_when_none_chosen(tmp_path, monkeypatch):
    app, window = _boot(tmp_path, monkeypatch, chain_id=None)
    from open_late.economy import economy_difficulty
    assert economy_difficulty(window.state) == "standard"
    window.close()


def test_picker_passes_stern_economy_into_new_game(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    window = MainWindow(SaveStore(tmp_path / "saves.sqlite"))
    window.show()
    app.processEvents()
    window._show_setup()
    window.name_input.setText("Retail Rivals")
    window.corporate_radio.setChecked(True)
    window.age_check.setChecked(True)
    window._show_picker()
    app.processEvents()
    assert window.economy_radios["standard"].isChecked()
    window.economy_radios["stern"].setChecked(True)
    app.processEvents()
    assert window._chosen_economy == "stern"
    window._start()
    app.processEvents()
    from open_late.economy import economy_difficulty
    assert economy_difficulty(window.state) == "stern"
    window.close()
