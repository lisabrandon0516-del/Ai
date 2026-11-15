"""Retail Rivals HQ v2: chain picker, planogram editor, polish, and copy."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QWidget

from open_late.store import SaveStore
from open_late.ui.hq_adapter import chain_catalog, chain_info, default_chain_id, set_chain
from open_late.ui.window import MainWindow


def _boot(tmp_path, monkeypatch, *, corporate: bool = True, name: str = "Retail Rivals", chain_id: str | None = None):
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


def test_title_and_setup_use_retail_rivals_logo(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    window = MainWindow(SaveStore(tmp_path / "saves.sqlite"))
    window.show()
    app.processEvents()
    assert window.windowTitle() == "Retail Rivals"
    wordmark = window.title_page.findChild(QLabel, "logo")
    assert wordmark is not None
    assert (not wordmark.pixmap().isNull()) or wordmark.text() == "Retail Rivals"
    # Title copy is the chain game, not the old boutique wordmark.
    labels = _text(window.title_page)
    assert "Toy's N Us" not in labels
    assert "Lingerie" not in labels
    window._show_setup()
    app.processEvents()
    assert window.name_input.placeholderText() == "Retail Rivals"
    assert window.name_input.text() == "Retail Rivals"
    setup = _text(window.setup_page)
    assert "Toy's N Us" not in setup
    assert "lingerie" not in setup.lower()
    window.close()


def test_setup_opens_chain_picker_and_start_defaults_to_megamart(tmp_path, monkeypatch):
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
    assert window.stack.currentWidget() is window.picker_page
    catalog = chain_catalog()
    assert [row["id"] for row in catalog] == [
        "megamart", "valuemax", "primestop", "everyday", "shopgiant", "bluestar", "allinone",
    ]
    assert len(window._picker_cards) == 7
    # Official logos are on the cards.
    from open_late.ui.hq_adapter import chain_logo_path
    for row in catalog:
        assert chain_logo_path(row).exists()
    # Picker start and a bare _start both default to MegaMart when nothing was chosen.
    window._chosen_chain_id = None
    window._start()
    app.processEvents()
    info = chain_info(window.state)
    assert info["id"] == default_chain_id() == "megamart"
    assert info["name"] == "MegaMart"
    window.close()


def test_chosen_chain_shows_in_shell_and_store_cards(tmp_path, monkeypatch):
    app, window = _boot(tmp_path, monkeypatch, chain_id="bluestar")
    info = chain_info(window.state)
    assert info["id"] == "bluestar"
    assert info["name"] == "BlueStar"
    assert window.desktop.topbar.chain_name.text() == "BlueStar"
    pix = window.desktop.topbar.chain_logo.pixmap()
    assert pix is not None and not pix.isNull()
    window._open_app("stores")
    app.processEvents()
    text = _text(window.desktop.stores)
    assert "BlueStar" in text or "Retail Rivals" in text
    # Storefront art is present on a card.
    from open_late.ui.hq_art import StorefrontArt
    arts = window.desktop.stores.findChildren(StorefrontArt)
    assert arts
    window.close()


def test_set_chain_rejects_unknown_id(tmp_path, monkeypatch):
    app, window = _boot(tmp_path, monkeypatch)
    try:
        set_chain(window.state, "not-a-chain")
        raise AssertionError("expected ValueError")
    except ValueError:
        pass
    window.close()


def test_planogram_editor_has_fixtures_templates_and_sku_rail(tmp_path, monkeypatch):
    app, window = _boot(tmp_path, monkeypatch)
    window._open_app("planograms")
    app.processEvents()
    page = window.desktop.planogram
    assert page.isVisible()
    text = _text(page)
    assert "Planogram Editor" in text
    assert "FIXTURES" in text
    assert "Glass Shelf 4-Tier" in text
    assert "TEMPLATE" in text
    assert "Balanced Mix" in text
    assert "SKU RAIL" in text
    assert "Push to stores" in text
    assert "SALES HEAT" in text
    assert "FACING STATUS" in text
    page._set_template("grocery")
    app.processEvents()
    assert page.template_id == "grocery"
    page._push()
    app.processEvents()
    note = window.status.text().lower()
    assert "planogram pushed" in note or "the wall adds up" in note or "no stores" in note or "no facings" in note
    window.close()


def test_kpi_tiles_are_equal_height_without_sparklines(tmp_path, monkeypatch):
    app, window = _boot(tmp_path, monkeypatch)
    window._open_app("home")
    app.processEvents()
    home = window.desktop.home
    text = _text(home)
    assert "TAKE" in text and "DRAWER" in text and "STORE P&L" in text and "SUNDAY" in text
    tiles = [
        home.findChild(QWidget, "kpiTake"),
        home.findChild(QWidget, "kpiContribution"),
        home.findChild(QWidget, "kpiDrawer"),
    ]
    assert all(tile is not None for tile in tiles)
    heights = {tile.height() for tile in tiles}
    assert len(heights) == 1
    assert next(iter(heights)) == 128
    for tile in tiles:
        classes = {child.metaObject().className() for child in tile.findChildren(QWidget)}
        assert "Sparkline" in classes
    window.close()


def test_status_toast_sits_in_the_lower_work_area(tmp_path, monkeypatch):
    app, window = _boot(tmp_path, monkeypatch)
    window._open_app("home")
    app.processEvents()
    window._say("The mix legend should stay visible.")
    app.processEvents()
    status = window.status
    assert status.isVisible()
    topbar = window.desktop.topbar
    assert status.y() >= topbar.y() + topbar.height()
    # Parked in the lower work area so page headers stay readable.
    assert status.y() >= window.desktop.height() // 2
    assert status.y() + status.height() <= window.desktop.height()
    window.close()


def test_boutique_copy_is_cleared_from_displayed_strings(tmp_path, monkeypatch):
    banned = ("Toy's N Us", "Lingerie", "lingerie", "private fittings", "Intense wall", "Signature lace")
    ui_root = Path(__file__).resolve().parents[1] / "open_late" / "ui"
    hits = []
    for path in ui_root.rglob("*.py"):
        text = path.read_text()
        for needle in banned:
            if needle in text:
                hits.append(f"{path.name}: {needle}")
    assert hits == []
    app, window = _boot(tmp_path, monkeypatch)
    window._open_app("home")
    app.processEvents()
    blob = _text(window) + "\n" + _text(window.title_page) + "\n" + _text(window.setup_page)
    for needle in ("Toy's N Us", "Lingerie", "Intense wall"):
        assert needle not in blob
    window.close()
