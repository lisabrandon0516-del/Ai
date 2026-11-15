"""HQ v3k2: Dashboard regional map keeps a true Albers land aspect."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication

from open_late.store import SaveStore
from open_late.ui.hq_art import StoreMap
from open_late.ui.us_states import project_region, region_aspect
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
    return app, window


def _resize(window, app, size):
    width, height = size
    window.setMinimumSize(1, 1)
    window.resize(width, height)
    app.processEvents()
    if hasattr(window, "desktop") and window.desktop is not None and hasattr(window.desktop, "layout_chrome"):
        window.desktop.layout_chrome()
    window.resize(width, height)
    app.processEvents()


def _aspect_close(drawn: float, source: float, tol: float = 0.03) -> bool:
    if source <= 0 or drawn <= 0:
        return False
    return abs(drawn - source) / source <= tol


def test_albers_keeps_relative_city_positions():
    seattle = project_region(-122.33, 47.61, "CONUS")
    houston = project_region(-95.37, 29.76, "CONUS")
    nyc = project_region(-74.0, 40.7, "CONUS")
    assert seattle[0] < houston[0] < nyc[0]
    assert houston[1] < seattle[1]
    anchorage = project_region(-149.90, 61.22, "AK")
    juneau = project_region(-134.42, 58.30, "AK")
    assert anchorage[0] < juneau[0]
    assert region_aspect("CONUS") > 1.2
    assert region_aspect("CONUS") < 2.2


def test_store_map_drawn_aspect_matches_source_at_both_sizes(tmp_path, monkeypatch):
    app, window = _boot(tmp_path, monkeypatch, size=(1366, 768))
    window._open_app("home")
    app.processEvents()
    store_map = window.desktop.home.findChild(StoreMap)
    assert store_map is not None
    source = store_map.source_map_aspect("CONUS")
    for size in ((1366, 768), (1100, 700)):
        _resize(window, app, size)
        window._open_app("home")
        app.processEvents()
        # Paint so visibleRegion / host rect is current.
        store_map.grab()
        drawn = store_map.drawn_map_aspect("CONUS")
        assert _aspect_close(drawn, source), (
            f"CONUS drawn aspect {drawn:.4f} != source {source:.4f} at {size}"
        )
        for region in ("AK", "HI"):
            inset_drawn = store_map.drawn_map_aspect(region)
            inset_source = store_map.source_map_aspect(region)
            assert _aspect_close(inset_drawn, inset_source, tol=0.05), (
                f"{region} drawn aspect {inset_drawn:.4f} != source {inset_source:.4f} at {size}"
            )
        # Inset frames themselves stay close to the projected land aspect.
        frames = store_map.inset_frames()
        for region, frame in frames.items():
            frame_aspect = frame.width() / max(1, frame.height())
            assert _aspect_close(frame_aspect, store_map.source_map_aspect(region), tol=0.12), (
                f"{region} frame aspect {frame_aspect:.4f} drifted from {store_map.source_map_aspect(region):.4f}"
            )
        host = store_map.visibleRegion().boundingRect()
        if not host.isValid():
            host = store_map.rect()
        used = store_map.conus_draw_rect()
        assert host.adjusted(-2, -2, 2, 2).contains(used)
        for pin in store_map.layout_pins():
            if pin["_region"] == "CONUS":
                assert store_map.conus_rect().adjusted(-8, -8, 8, 8).contains(pin["_point"])
                assert not frames["AK"].contains(pin["_point"])
                assert not frames["HI"].contains(pin["_point"])
            elif pin["_region"] in frames:
                assert frames[pin["_region"]].adjusted(0, 0, 0, 0).contains(pin["_point"])
        # Callouts stay inside the visible card.
        for pin in store_map.layout_pins():
            call = pin.get("_callout")
            if call:
                from PySide6.QtCore import QRect
                box = QRect(*call)
                assert host.adjusted(-2, -2, 2, 2).contains(box), (pin.get("id"), box, host)
    window.close()


def test_standalone_map_letterboxes_instead_of_stretching():
    app = QApplication.instance() or QApplication([])
    widget = StoreMap(theme="dark")
    # A wide, short canvas like the dashboard card — this used to stretch CONUS.
    widget.resize(900, 280)
    widget.show()
    app.processEvents()
    widget.grab()
    source = widget.source_map_aspect("CONUS")
    drawn = widget.drawn_map_aspect("CONUS")
    assert _aspect_close(drawn, source)
    used = widget.conus_draw_rect()
    host = widget.rect()
    # Side or top/bottom letterbox must exist on a ~3.2:1 card vs a ~1.6:1 map.
    assert used.width() < host.width() or used.height() < host.height()
    assert used.width() / max(1, used.height()) == drawn or _aspect_close(used.width() / max(1, used.height()), source)
    widget.close()
