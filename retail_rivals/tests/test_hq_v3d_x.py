"""HQ v3d: storefront badges on the dashboard map, plus Alaska and Hawaii insets."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QRegion
from PySide6.QtWidgets import QApplication, QToolTip

from open_late.store import SaveStore
from open_late.ui.hq_art import StoreMap, draw_store_badge, store_badge_rect
from open_late.ui.theme import DASH_PIN_HIGH, DASH_PIN_LOW, DASH_PIN_MID
from open_late.ui.us_states import INSET_STATES, STATE_RINGS, region_for_lonlat
from open_late.ui.window import MainWindow


def _app(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


def _boot(tmp_path, monkeypatch, size=(1366, 768)):
    app = _app(monkeypatch)
    window = MainWindow(SaveStore(tmp_path / "saves.sqlite"))
    window.show()
    window.resize(*size)
    app.processEvents()
    window._show_setup()
    window.name_input.setText("Retail Rivals")
    window.corporate_radio.setChecked(True)
    window.age_check.setChecked(True)
    window._chosen_chain_id = "bluestar"
    window._start()
    app.processEvents()
    return app, window


def _color_at(image: QImage, x: int, y: int) -> QColor:
    return QColor(image.pixel(x, y))


def _close_to(color: QColor, target: QColor, tol: int = 70) -> bool:
    return (
        abs(color.red() - target.red()) <= tol
        and abs(color.green() - target.green()) <= tol
        and abs(color.blue() - target.blue()) <= tol
    )


def test_region_helper_routes_alaska_hawaii_and_conus():
    assert region_for_lonlat(-149.90, 61.22) == "AK"  # Anchorage
    assert region_for_lonlat(-157.86, 21.31) == "HI"  # Honolulu
    assert region_for_lonlat(-134.42, 58.30) == "AK"  # Juneau
    assert region_for_lonlat(-122.33, 47.61) == "CONUS"  # Seattle
    assert region_for_lonlat(-95.37, 29.76) == "CONUS"  # Houston
    # Dateline Aleutians should still count as Alaska, not the CONUS map.
    assert region_for_lonlat(177.50, 51.90) == "AK"
    assert INSET_STATES == frozenset({"AK", "HI"})
    assert "AK" in STATE_RINGS and "HI" in STATE_RINGS


def test_storefront_badge_uses_status_color_and_is_not_a_dot():
    app = QApplication.instance() or QApplication([])
    size = 22
    image = QImage(64, 64, QImage.Format.Format_ARGB32)
    image.fill(QColor("#09152D"))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    center = QPoint(32, 32)
    color = QColor(DASH_PIN_LOW)
    rect = draw_store_badge(painter, center, color, size=size)
    painter.end()
    assert rect == store_badge_rect(center, size)
    # The badge fill should carry the status color near the rim (not only a tiny center dot).
    sample = _color_at(image, center.x(), rect.y() + 3)
    # top edge may be antialiased; sample a mid-side point on the fill
    side = _color_at(image, rect.x() + 3, center.y())
    assert _close_to(side, color) or _close_to(sample, color)
    # A circle of radius size/2 would miss the square's diagonal corner band;
    # a rounded-rect badge still covers a point ~0.72 of the half-width along the diagonal.
    # That point is inside a square (and a rounded square with radius ~0.22*size)
    # but outside a circle of radius size/2.
    dx = int(round((size / 2) * 0.72))
    corner = _color_at(image, center.x() + dx, center.y() + dx)
    bg = QColor("#09152D")
    # The corner band should not be the empty map background — this is a badge, not a disc.
    assert not _close_to(corner, bg, tol=30)
    # And green / yellow badges also keep their own fill color.
    for name, hex_color in (("high", DASH_PIN_HIGH), ("mid", DASH_PIN_MID)):
        image.fill(QColor("#09152D"))
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        draw_store_badge(painter, center, QColor(hex_color), size=size)
        painter.end()
        side = _color_at(image, rect.x() + 3, center.y())
        assert _close_to(side, QColor(hex_color)), name


def test_inset_pins_land_inside_ak_and_hi_frames():
    app = QApplication.instance() or QApplication([])
    widget = StoreMap(theme="dark")
    widget.resize(760, 340)
    widget.set_pins([
        {"id": "seattle", "label": "Seattle", "lon": -122.33, "lat": 47.61, "owned": True, "rank": "high", "tip": "Seattle"},
        {"id": "anchorage", "label": "Anchorage", "lon": -149.90, "lat": 61.22, "owned": True, "rank": "mid", "tip": "Anchorage"},
        {"id": "honolulu", "label": "Honolulu", "lon": -157.86, "lat": 21.31, "owned": True, "rank": "low", "tip": "Honolulu"},
        {"id": "juneau", "label": "Juneau", "lon": -134.42, "lat": 58.30, "owned": True, "rank": "mid", "tip": "Juneau"},
    ])
    widget.show()
    app.processEvents()
    frames = widget.inset_frames()
    conus = widget.conus_rect()
    assert frames["AK"].isValid() and frames["HI"].isValid()
    # Usual Census shelf: Alaska on the left, Hawaii to its right, both in the lower left.
    assert frames["AK"].left() < frames["HI"].left()
    assert frames["AK"].bottom() >= widget.height() - 16
    assert frames["HI"].bottom() >= widget.height() - 16
    assert frames["AK"].left() <= 16
    # The 48 are shifted so the west/southwest coast is not under the inset frames.
    from open_late.ui.hq_art import _project
    for lon, lat in ((-117.1, 32.5), (-124.4, 40.4), (-114.7, 32.7)):
        point = _project(lon, lat, conus)
        assert not frames["AK"].contains(point)
        assert not frames["HI"].contains(point)
    laid = {pin["id"]: pin for pin in widget.layout_pins()}
    assert laid["anchorage"]["_region"] == "AK"
    assert laid["honolulu"]["_region"] == "HI"
    assert laid["juneau"]["_region"] == "AK"
    assert laid["seattle"]["_region"] == "CONUS"
    assert frames["AK"].adjusted(2, 2, -2, -2).contains(laid["anchorage"]["_point"])
    assert frames["AK"].adjusted(2, 2, -2, -2).contains(laid["juneau"]["_point"])
    assert frames["HI"].adjusted(2, 2, -2, -2).contains(laid["honolulu"]["_point"])
    assert conus.contains(laid["seattle"]["_point"])
    assert not frames["AK"].contains(laid["seattle"]["_point"])
    assert not frames["HI"].contains(laid["seattle"]["_point"])
    # Anchorage (south-central) should sit west of Juneau (the panhandle) inside the inset.
    assert laid["anchorage"]["_point"].x() < laid["juneau"]["_point"].x()
    widget.close()


def test_clustered_pins_offset_or_show_a_count():
    app = QApplication.instance() or QApplication([])
    widget = StoreMap(theme="dark")
    widget.resize(760, 340)
    # Two doors on the same Houston block, plus two nearby Dallas-area stores
    # far enough apart to project to different pixels but close enough to cluster.
    widget.set_pins([
        {"id": "h1", "label": "Houston A", "lon": -95.370, "lat": 29.760, "owned": True, "rank": "high", "tip": "A"},
        {"id": "h2", "label": "Houston B", "lon": -95.370, "lat": 29.760, "owned": True, "rank": "mid", "tip": "B"},
        {"id": "d1", "label": "Dallas A", "lon": -96.80, "lat": 32.78, "owned": True, "rank": "low", "tip": "D1"},
        {"id": "d2", "label": "Dallas B", "lon": -97.10, "lat": 32.90, "owned": True, "rank": "mid", "tip": "D2"},
    ])
    widget.show()
    app.processEvents()
    laid = widget.layout_pins()
    by_id = {pin["id"]: pin for pin in laid}
    # Exact overlaps share a badge and advertise the stack count.
    assert by_id["h1"]["_point"] == by_id["h2"]["_point"]
    assert by_id["h1"]["_count"] == 2 and by_id["h2"]["_count"] == 2
    # Nearby-but-distinct stores are fanned apart instead of stacked.
    assert by_id["d1"]["_count"] == 1 and by_id["d2"]["_count"] == 1
    assert by_id["d1"]["_point"] != by_id["d2"]["_point"]
    # The fan should actually move them off their raw projections.
    assert by_id["d1"]["_point"] != by_id["d1"]["_raw"] or by_id["d2"]["_point"] != by_id["d2"]["_raw"]
    # All three badges stay on the CONUS map and are clickable.
    for pin in laid:
        assert widget.conus_rect().adjusted(-12, -12, 12, 12).contains(pin["_point"])
        found = widget._pin_at(pin["_point"])
        assert found is not None
    widget.close()


def test_hover_tooltip_and_click_still_work(qt_signal=None):
    app = QApplication.instance() or QApplication([])
    widget = StoreMap(theme="dark")
    widget.resize(760, 340)
    clicks: list[str] = []
    signs: list[str] = []
    widget.store_clicked.connect(clicks.append)
    widget.sign_requested.connect(signs.append)
    widget.set_pins([
        {"id": "seattle", "label": "Seattle", "lon": -122.33, "lat": 47.61, "owned": True, "rank": "high", "tip": "Seattle · owned"},
        {"id": "anchorage", "label": "Anchorage", "lon": -149.90, "lat": 61.22, "owned": False, "tip": "Anchorage · not leased"},
    ])
    widget.show()
    app.processEvents()
    laid = {pin["id"]: pin for pin in widget.layout_pins()}
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtCore import QEvent, QPointF

    def click(point: QPoint):
        event = QMouseEvent(
            QEvent.Type.MouseButtonPress,
            QPointF(point),
            QPointF(point),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        widget.mousePressEvent(event)

    def move(point: QPoint):
        event = QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(point),
            QPointF(point),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
        widget.mouseMoveEvent(event)

    move(laid["seattle"]["_point"])
    assert widget._hover == "seattle"
    assert "Seattle" in widget.toolTip()
    click(laid["seattle"]["_point"])
    assert clicks == ["seattle"]
    move(laid["anchorage"]["_point"])
    assert widget._hover == "anchorage"
    assert "not leased" in widget.toolTip()
    click(laid["anchorage"]["_point"])
    assert signs == ["anchorage"]
    widget.close()


def test_dashboard_map_shows_badges_and_insets(tmp_path, monkeypatch):
    app, window = _boot(tmp_path, monkeypatch, size=(1366, 768))
    window._open_app("home")
    app.processEvents()
    store_map = window.desktop.home.findChild(StoreMap)
    assert store_map is not None
    frames = store_map.inset_frames()
    assert frames["AK"].isValid() and frames["HI"].isValid()
    laid = store_map.layout_pins()
    assert laid, "dashboard should still pin the chain's cities"
    # Every live city in the starter set is CONUS; badges must land on the main map.
    for pin in laid:
        assert pin["_region"] == "CONUS"
        assert store_map.conus_rect().adjusted(-8, -8, 8, 8).contains(pin["_point"])
        assert pin.get("_badge") is not None
    # Insets stay in the lower left of the visible map (the widget may be taller
    # than the card on a tight dashboard) and do not swallow the CONUS pins.
    visible = store_map.visibleRegion().boundingRect()
    assert frames["AK"].left() < frames["HI"].left()
    assert frames["AK"].bottom() >= visible.bottom() - 20
    assert frames["AK"].bottom() <= visible.bottom()
    window.resize(1100, 700)
    if hasattr(window, "desktop") and window.desktop is not None:
        window.desktop.layout_chrome()
    app.processEvents()
    frames = store_map.inset_frames()
    assert frames["AK"].isValid() and frames["HI"].width() >= 80
    for pin in store_map.layout_pins():
        assert store_map.conus_rect().adjusted(-8, -8, 8, 8).contains(pin["_point"])
    window.close()
