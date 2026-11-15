"""HQ v3k3: insets sit under CONUS, callout misses states, pins do not overlap."""

from __future__ import annotations

from PySide6.QtCore import QRect
from PySide6.QtWidgets import QApplication, QWidget

from open_late.store import SaveStore
from open_late.ui.hq_art import INSET_GUTTER, StoreMap
from open_late.ui.window import MainWindow


def _app(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


def _boot(tmp_path, monkeypatch, size=(1366, 768)):
    app = _app(monkeypatch)
    window = MainWindow(SaveStore(tmp_path / "saves.sqlite"))
    window.show()
    window.setMinimumSize(1, 1)
    window.resize(*size)
    app.processEvents()
    window._show_setup()
    window.name_input.setText("Retail Rivals")
    window.corporate_radio.setChecked(True)
    window.age_check.setChecked(True)
    window._chosen_chain_id = "bluestar"
    window._chosen_economy = "standard"
    window._start()
    app.processEvents()
    window._to_desk()
    app.processEvents()
    return app, window


def _resize(window, app, size):
    width, height = size
    window.setMinimumSize(1, 1)
    window.resize(width, height)
    app.processEvents()
    if getattr(window, "desktop", None) is not None and hasattr(window.desktop, "layout_chrome"):
        window.desktop.layout_chrome()
    home = getattr(window.desktop, "home", None)
    if home is not None and hasattr(home, "_apply_map_height"):
        home._apply_map_height()
    window.resize(width, height)
    app.processEvents()


def _map_at(window, app, size) -> StoreMap:
    _resize(window, app, size)
    window._open_app("home")
    app.processEvents()
    store_map = window.desktop.home.findChild(StoreMap)
    assert store_map is not None
    # Paint so visibleRegion / host rect is current.
    store_map.grab()
    return store_map


def _unique_pin_rects(store_map: StoreMap) -> list[QRect]:
    seen = []
    keys = set()
    for pin in store_map.layout_pins():
        badge = pin.get("_badge")
        if badge is None:
            continue
        rect = QRect(badge)
        key = (rect.x(), rect.y(), rect.width(), rect.height())
        if key in keys:
            continue
        keys.add(key)
        seen.append(rect)
    return seen


def test_insets_sit_below_conus_without_overlap_at_both_sizes(tmp_path, monkeypatch):
    app, window = _boot(tmp_path, monkeypatch, size=(1366, 768))
    for size in ((1366, 768), (1100, 700)):
        store_map = _map_at(window, app, size)
        bounds = store_map.conus_bounds_rect()
        used = store_map.conus_draw_rect()
        assert bounds.isValid() and used.isValid()
        frames = store_map.inset_frames()
        assert "AK" in frames and "HI" in frames
        for name, frame in frames.items():
            assert frame.isValid() and frame.width() >= 40 and frame.height() >= 28, (size, name, frame)
            assert not frame.intersects(bounds), (size, name, frame, bounds)
            assert not frame.intersects(used), (size, name, frame, used)
            assert frame.top() >= bounds.bottom() + 1, (size, name, frame.top(), bounds.bottom())
            assert frame.top() >= used.bottom() + 1, (size, name, frame.top(), used.bottom())
            # A clear gutter, not just a shared edge.
            assert frame.top() >= bounds.bottom() + max(6, INSET_GUTTER - 4), (
                size, name, frame.top(), bounds.bottom()
            )
        # AK left of HI, both bottom-left of the card, HI does not sit on top of AK.
        ak, hi = frames["AK"], frames["HI"]
        assert ak.left() < hi.left()
        assert not ak.intersects(hi)
        host = store_map.visibleRegion().boundingRect()
        if not host.isValid():
            host = store_map.rect()
        mid = host.center().x()
        assert ak.left() < mid and hi.left() < mid
    window.close()


def test_callout_misses_state_polygons_at_both_sizes(tmp_path, monkeypatch):
    app, window = _boot(tmp_path, monkeypatch, size=(1366, 768))
    for size in ((1366, 768), (1100, 700)):
        store_map = _map_at(window, app, size)
        box = store_map.layout_callout()
        assert box is not None and box.isValid(), size
        host = store_map.visibleRegion().boundingRect()
        if not host.isValid():
            host = store_map.rect()
        assert host.adjusted(-2, -2, 2, 2).contains(box), (size, box, host)
        assert not store_map.callout_hits_states(box), (size, box)
        # One callout only, and it belongs to Evansville or the selected store.
        pin = store_map.primary_callout_pin()
        assert pin is not None
        assert pin.get("owned")
        ident = str(pin.get("id") or "")
        if not pin.get("selected"):
            assert ident == "evansville"
        # Leader lives with the callout layout; the rect itself stays in the card.
        assert pin.get("_callout") == (box.x(), box.y(), box.width(), box.height())
    window.close()


def test_pin_rects_do_not_overlap_at_both_sizes(tmp_path, monkeypatch):
    app, window = _boot(tmp_path, monkeypatch, size=(1366, 768))
    for size in ((1366, 768), (1100, 700)):
        store_map = _map_at(window, app, size)
        rects = _unique_pin_rects(store_map)
        assert len(rects) >= 2, size
        labels = {
            (pin.get("_badge").x(), pin.get("_badge").y()): pin.get("label")
            for pin in store_map.layout_pins()
            if pin.get("_badge") is not None
        }
        for i, a in enumerate(rects):
            for b in rects[i + 1:]:
                assert not a.intersects(b), (size, labels.get((a.x(), a.y()), a), labels.get((b.x(), b.y()), b), a, b)
        # Evansville and Naperville must be distinct, non-overlapping badges.
        laid = {str(pin.get("id") or ""): pin for pin in store_map.layout_pins()}
        if "evansville" in laid and "naperville" in laid:
            ev = QRect(laid["evansville"]["_badge"])
            nv = QRect(laid["naperville"]["_badge"])
            assert ev != nv
            assert not ev.intersects(nv)
            # Naperville (Chicago) stays north of Evansville (southern Indiana).
            assert laid["naperville"]["_point"].y() < laid["evansville"]["_point"].y()
    window.close()


def test_dashboard_map_is_tall_and_cards_fit_at_both_sizes(tmp_path, monkeypatch):
    app, window = _boot(tmp_path, monkeypatch, size=(1366, 768))
    names = (
        "kpiTake",
        "kpiContribution",
        "kpiDrawer",
        "economyNews",
        "mapCard",
        "marketingCard",
        "perfCard",
        "planoPreview",
        "revenueCard",
    )
    floors = {(1366, 768): 210, (1100, 700): 160}
    for size in ((1366, 768), (1100, 700)):
        store_map = _map_at(window, app, size)
        home = window.desktop.home
        area = window.desktop.work_area()
        for name in names:
            widget = home.findChild(QWidget, name)
            assert widget is not None, (size, name)
            top_left = widget.mapTo(window.desktop, widget.rect().topLeft())
            rect = QRect(top_left, widget.size())
            assert area.adjusted(-2, -2, 2, 2).contains(rect), (size, name, rect, area)
        visible = store_map.visibleRegion().boundingRect()
        if not visible.isValid():
            visible = store_map.rect()
        assert visible.height() >= floors[size], (size, visible.height(), store_map.height())
        # Insets and CONUS both have a usable slice of that taller card.
        used = store_map.conus_draw_rect()
        frames = store_map.inset_frames()
        assert used.height() >= 90, (size, used)
        assert frames["AK"].height() >= 32
    window.close()
