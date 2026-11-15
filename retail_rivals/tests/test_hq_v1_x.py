"""HQ Phase 1 shell, dashboard, stores portfolio, and store switcher."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication, QLabel, QWidget

from open_late.store import SaveStore
from open_late.ui.hq_adapter import (
    chain_board,
    hq_available,
    install_fee,
    pos_options,
    store_ids,
    store_pnl,
    store_pos,
)
from open_late.ui.hq_shell import RAIL_ITEMS
from open_late.ui.window import MainWindow


def _boot(tmp_path, monkeypatch, *, corporate: bool = True, name: str = "Retail Rivals"):
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
    window._start()
    app.processEvents()
    return app, window


def _text(widget) -> str:
    parts = []
    if isinstance(widget, QLabel):
        parts.append(widget.text())
    for child in widget.findChildren(QLabel):
        parts.append(child.text())
    return "\n".join(parts)


def test_shell_has_rail_topbar_and_one_pane(tmp_path, monkeypatch):
    app, window = _boot(tmp_path, monkeypatch)
    desktop = window.desktop
    assert desktop.objectName() == "hqShell"
    assert desktop.rail.objectName() == "hqRail"
    assert desktop.topbar.objectName() == "hqTopBar"
    assert desktop.findChild(type(desktop), "hqMain") is not None or desktop.body.objectName() == "hqBody"
    assert not hasattr(desktop, "wm") or getattr(desktop, "wm", None) is None
    assert not hasattr(desktop, "taskbar")
    assert desktop.current_page() == "home"
    assert desktop.home.isVisible()
    assert desktop.rail.isVisible()
    assert desktop.topbar.isVisible()
    assert desktop.topbar.switcher.objectName() == "scopeBtn"
    assert desktop.topbar.alerts.objectName() == "alertsBtn"
    assert desktop.topbar.to_desk.isVisible()
    assert window.windowTitle() == "Retail Rivals"
    logo = desktop.rail.logo
    assert logo is not None
    assert logo.toolTip() == "Retail Rivals"
    assert (not logo.pixmap().isNull()) or logo.text() == "Retail Rivals"
    window.close()


def test_navigates_each_module(tmp_path, monkeypatch):
    app, window = _boot(tmp_path, monkeypatch)
    window._to_desk()
    app.processEvents()
    ids = [item[0] for item in RAIL_ITEMS]
    for app_id in ids:
        window._open_app(app_id)
        app.processEvents()
        assert window.desktop.current_page() == app_id, app_id
        if app_id == "home":
            assert window.desktop.home.isVisible()
        elif app_id == "stores":
            assert window.desktop.stores.isVisible()
        elif app_id == "pos":
            assert window.desktop.pos_page.isVisible()
        elif app_id == "planograms":
            assert window.desktop.planogram.isVisible()
        elif app_id == "economy":
            assert window.desktop.economy.isVisible()
        else:
            assert window.desktop.module_scroll.isVisible(), app_id
    window.close()


def test_store_switcher_scopes_modules(tmp_path, monkeypatch):
    app, window = _boot(tmp_path, monkeypatch)
    window._to_desk()
    app.processEvents()
    shell = window.desktop
    shell.set_scope("all")
    app.processEvents()
    assert shell.scope == ("all", None)
    assert "All stores" in shell.scope_text()
    assert "All stores" in shell.topbar.breadcrumb.text()

    ids = store_ids(window.state)
    assert ids[0] == "evansville"
    shell.set_scope("store", "evansville")
    app.processEvents()
    assert shell.scope == ("store", "evansville")
    assert "Evansville" in shell.scope_text()
    window._open_app("inventory")
    app.processEvents()
    assert "Evansville warehouse" in _text(shell.module_inner)

    from open_late.ui.hq_adapter import regions_for

    regions = regions_for(window.state)
    assert regions
    shell.set_scope("region", regions[0])
    app.processEvents()
    assert shell.scope == ("region", regions[0])
    assert regions[0] in shell.scope_text()
    window.close()


def test_dashboard_renders_kpis_and_queue(tmp_path, monkeypatch):
    app, window = _boot(tmp_path, monkeypatch)
    window._open_app("home")
    app.processEvents()
    home = window.desktop.home
    assert home.isVisible()
    text = _text(home)
    assert "STORE P&L" in text
    assert "TAKE" in text
    assert "DRAWER" in text
    assert "SUNDAY" in text
    assert home.findChild(QWidget, "kpiTake") is not None
    assert home.findChild(QWidget, "kpiContribution") is not None
    assert home.findChild(QWidget, "todoQueue") is not None
    names = {child.objectName() for child in home.findChildren(QWidget)}
    assert "lineChart" in names
    assert "barChart" in names
    assert "mixLegend" in names
    if hq_available():
        assert "will not match a door's last-week contribution" in text or "Store P&L" in text
    else:
        assert "placeholder" in text.lower() or "waits on the engine" in text.lower()
    window.close()


def test_stores_grid_map_and_drawer(tmp_path, monkeypatch):
    app, window = _boot(tmp_path, monkeypatch)
    window._open_app("stores")
    app.processEvents()
    page = window.desktop.stores
    assert page.isVisible()
    assert page.map.isVisible()
    assert page.grid_host.isVisible()
    assert page.drawer.isVisible()
    assert page.grid_host.objectName() == "storeGrid"
    assert page.map.objectName() == "storeMap"
    assert page.drawer.objectName() == "storeDrawer"
    assert page.grid.count() >= 1
    text = _text(page)
    assert "Evansville" in text
    drawer = _text(page.drawer)
    assert "Evansville" in drawer
    assert "Last week contribution" in drawer
    assert "Store P&L" in drawer
    assert "POS" in drawer
    assert "install fee today" in drawer
    assert "next Sunday close" in drawer
    assert page.drawer.findChild(type(page.drawer), "posSwitchHint") is not None or "Open Drawer $200" in drawer
    # The two numbers are labeled separately, not presented as one figure.
    assert "Last week contribution" in drawer and "Store P&L" in drawer
    window.close()


def test_pos_page_lists_tills_and_fees(tmp_path, monkeypatch):
    app, window = _boot(tmp_path, monkeypatch)
    window._open_app("pos")
    app.processEvents()
    page = window.desktop.pos_page
    assert page.isVisible()
    text = _text(page)
    assert "Open Drawer" in text
    assert "Counter Ledger" in text
    assert "Chain Link" in text
    assert "install fee today" in text
    assert "next Sunday close" in text
    assert "$200" in text and "$350" in text and "$800" in text
    window.close()


def test_adapter_matches_published_shape(tmp_path, monkeypatch):
    app, window = _boot(tmp_path, monkeypatch)
    state = window.state
    ids = store_ids(state)
    assert ids[0] == "evansville"
    assert "evansville" in ids
    options = pos_options()
    assert [row["id"] for row in options] == ["open_drawer", "counter_ledger", "chain_link"]
    assert install_fee("open_drawer") == 200
    assert install_fee("counter_ledger") == 350
    assert install_fee("chain_link") == 800
    pos = store_pos(state, "evansville")
    assert pos["name"]
    assert pos.get("id") in {"open_drawer", "counter_ledger", "chain_link", None} or pos["name"] == "Counter Ledger"
    if not pos.get("placeholder"):
        assert pos["id"] == "counter_ledger"
    pnl = store_pnl(state, "evansville")
    for key in ("sales", "cogs", "labor", "rent", "freight", "shrink", "card_fees", "pos_fees", "contribution"):
        assert key in pnl
    board = chain_board(state)
    assert board
    assert board[-1]["store_id"] == "chain"
    window.close()


def test_shop_mode_store_id_is_evansville(tmp_path, monkeypatch):
    app, window = _boot(tmp_path, monkeypatch, corporate=False, name="Ledger")
    assert store_ids(window.state) == ["evansville"]
    window._open_app("home")
    app.processEvents()
    assert window.desktop.current_page() == "home"
    window.close()


def test_brand_logo_ships_in_assets(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from open_late.ui.hq_shell import BRAND_LOGO, brand_logo_pixmap
    QApplication.instance() or QApplication([])
    assert BRAND_LOGO.exists()
    assert BRAND_LOGO.stat().st_size > 1000
    pix = brand_logo_pixmap(196, 88)
    assert not pix.isNull()
    assert pix.width() <= 196 and pix.height() <= 88
