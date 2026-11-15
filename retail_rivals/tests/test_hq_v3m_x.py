"""HQ v3m: compact store drawer, expansion offer cards, off-land map leader, labor cap."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRect
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QWidget,
)

from open_late.store import SaveStore
from open_late.ui.hq_art import StoreMap
from open_late.ui.hq_pages import labor_budget_ceiling
from open_late.ui.us_states import CONTERMINOUS
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
    window.setMinimumSize(1, 1)
    window.resize(*size)
    app.processEvents()
    return app, window


def _resize(window, app, size):
    window.setMinimumSize(1, 1)
    window.resize(*size)
    app.processEvents()
    if getattr(window, "desktop", None) is not None and hasattr(window.desktop, "layout_chrome"):
        window.desktop.layout_chrome()
    window.resize(*size)
    app.processEvents()


def test_labor_budget_ceiling_uses_constant_and_fallback(monkeypatch):
    try:
        from open_late.finance import LABOR_BUDGET_DEFAULT
        present = True
        assert labor_budget_ceiling(0) >= int(LABOR_BUDGET_DEFAULT)
    except ImportError:
        present = False
    assert labor_budget_ceiling(0) >= 180_000
    assert labor_budget_ceiling(250_000) == 250_000
    import open_late.finance as finance
    monkeypatch.delattr(finance, "LABOR_BUDGET_DEFAULT", raising=False)
    assert labor_budget_ceiling(0) >= 180_000
    if present:
        monkeypatch.setattr(finance, "LABOR_BUDGET_DEFAULT", 220_000, raising=False)
        assert labor_budget_ceiling(0) == 220_000
        assert labor_budget_ceiling(300_000) == 300_000


def test_drawer_labor_and_legacy_spin_allow_default_budget(tmp_path, monkeypatch):
    app, window = _boot(tmp_path, monkeypatch, mode="corporate")
    window._open_app("stores")
    app.processEvents()
    page = window.desktop.stores
    if not page.selected and window.state.doors:
        page.select_store(window.state.doors[0].id)
        app.processEvents()
    labor = page.findChild(QSpinBox, "laborBudget")
    assert labor is not None
    assert labor.maximum() >= 180_000
    assert labor.maximum() >= labor_budget_ceiling(window.state.doors[0].labor_budget)
    assert labor.value() == window.state.doors[0].labor_budget
    window.close()


def test_switch_till_and_profile_sit_above_the_fold(tmp_path, monkeypatch):
    app, window = _boot(tmp_path, monkeypatch, mode="corporate", size=(1366, 768))
    window._open_app("stores")
    app.processEvents()
    page = window.desktop.stores
    if not page.selected and window.state.doors:
        page.select_store(window.state.doors[0].id)
        app.processEvents()
    scroll = page.drawer.findChild(QScrollArea, "storeDrawerScroll")
    assert scroll is not None
    viewport = scroll.viewport()
    assert scroll.verticalScrollBar().maximum() == 0
    switch = page.findChild(QPushButton, "primary")
    profile = page.findChild(QPushButton, "viewProfile")
    assert switch is not None and profile is not None
    assert "Switch till" in switch.text()
    assert "View full profile" in profile.text()
    for btn in (switch, profile):
        top = btn.mapTo(viewport, btn.rect().topLeft())
        bot = btn.mapTo(viewport, btn.rect().bottomRight())
        assert viewport.rect().contains(top), (btn.objectName(), top, viewport.rect())
        assert viewport.rect().contains(bot), (btn.objectName(), bot, viewport.rect())
        assert btn.height() >= 32
        assert btn.width() >= 80
    # Labels on the truck row stay fully visible too.
    truck = page.findChild(QPushButton, "sendTruck")
    fill = page.findChild(QPushButton, "replenishDoor")
    assert truck.text() == "Send truck"
    assert fill.text() == "Replenish"
    window.close()


def test_expansion_offer_cards_match_portfolio_style(tmp_path, monkeypatch):
    app, window = _boot(tmp_path, monkeypatch, mode="shop", chain="megamart")
    window._open_app("expansion")
    app.processEvents()
    cards = [
        widget for widget in window.findChildren(QWidget)
        if widget.objectName() == "storeCard" and widget.property("offerId")
    ]
    assert len(cards) >= 1
    for card in cards:
        title = card.findChild(QLabel, "offerTitle")
        assert title is not None and title.text().strip()
        assert title.width() >= 80
        sign = None
        for btn in card.findChildren(QPushButton):
            if btn.text().startswith("Sign for "):
                sign = btn
                break
        assert sign is not None, card.property("offerId")
        assert "Sign for " in sign.text()
        # Full label, not clipped to a sliver.
        assert sign.height() >= 28
        assert sign.width() >= 120
        fm = sign.fontMetrics()
        assert fm.horizontalAdvance(sign.text()) <= sign.width()
    window.close()


def _leader_hits_foreign_polygons(store_map: StoreMap, points, pin, slop: float = 2.5) -> list[tuple]:
    abbr = store_map.pin_state_abbr(pin)
    badge = pin.get("_badge")
    conus = store_map.conus_rect()
    own = store_map._path_for(abbr, conus, inset=False) if abbr else None
    foreign = []
    for name in CONTERMINOUS:
        if name == abbr:
            continue
        path = store_map._path_for(name, conus, inset=False)
        if not path.isEmpty():
            foreign.append((name, path))
    hits = []
    for start, end in zip(points, points[1:]):
        steps = max(abs(end.x() - start.x()), abs(end.y() - start.y()), 1)
        for index in range(steps + 1):
            x = start.x() + (end.x() - start.x()) * index / steps
            y = start.y() + (end.y() - start.y()) * index / steps
            point = QPointF(x, y)
            ix, iy = int(round(x)), int(round(y))
            if badge is not None and QRect(badge).adjusted(-2, -2, 2, 2).contains(ix, iy):
                continue
            if own is not None and own.contains(point):
                continue
            for name, path in foreign:
                if not path.contains(point):
                    continue
                near_ok = False
                for dx, dy in (
                    (slop, 0), (-slop, 0), (0, slop), (0, -slop),
                    (slop, slop), (-slop, -slop), (slop, -slop), (-slop, slop),
                ):
                    probe = QPointF(x + dx, y + dy)
                    if own is not None and own.contains(probe):
                        near_ok = True
                        break
                    if not any(other.contains(probe) for _n, other in foreign):
                        near_ok = True
                        break
                if not near_ok:
                    hits.append((name, ix, iy))
                    if len(hits) > 6:
                        return hits
    return hits


def test_leader_path_stays_off_foreign_states_at_both_sizes(tmp_path, monkeypatch):
    app, window = _boot(tmp_path, monkeypatch, mode="corporate", size=(1366, 768))
    for size in ((1366, 768), (1100, 700)):
        _resize(window, app, size)
        window._open_app("stores")
        app.processEvents()
        store_map = window.desktop.stores.findChild(StoreMap)
        assert store_map is not None, size
        store_map.grab()
        box = store_map.layout_callout()
        pin = store_map.primary_callout_pin()
        assert box is not None and pin is not None, size
        points = store_map.leader_points(pin, box)
        assert len(points) >= 2, size
        assert not store_map.leader_hits_foreign_states(points, pin), (size, points)
        hits = _leader_hits_foreign_polygons(store_map, points, pin)
        assert hits == [], (size, hits, [(p.x(), p.y()) for p in points])
    window.close()
