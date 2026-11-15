"""HQ v2c: large Census-outline map, margin KPI, neon trend, table deltas, economy news."""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QPushButton, QWidget

from open_late.store import SaveStore
from open_late.ui.hq_pages import KpiIcon, LineChart
from open_late.ui.hq_art import StoreMap
from open_late.ui.theme import DASH_BG, DASH_PIN_HIGH, DASH_PIN_LOW, DASH_PIN_MID
from open_late.ui.us_states import CONTERMINOUS, STATE_RINGS
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


def test_us_states_are_census_derived_and_detailed():
    import open_late.ui.us_states as mod
    source = (mod.__doc__ or "") + (mod.__file__ and open(mod.__file__).read(2000) or "")
    assert "Census" in source or "census" in source
    assert "public domain" in source.lower() or "public-domain" in source.lower()
    assert len(STATE_RINGS) == 51
    assert "DC" in STATE_RINGS and "CA" in STATE_RINGS and "TX" in STATE_RINGS
    assert "AK" in STATE_RINGS and "HI" in STATE_RINGS
    assert set(CONTERMINOUS).isdisjoint({"AK", "HI"})
    assert set(STATE_RINGS) == set(CONTERMINOUS) | {"AK", "HI"}
    # Not the old blocky 5-point rectangles: coasts keep real vertices.
    assert sum(len(ring) for ring in STATE_RINGS["CA"]) >= 40
    assert sum(len(ring) for ring in STATE_RINGS["FL"]) >= 40
    assert sum(len(ring) for ring in STATE_RINGS["MI"]) >= 40
    assert len(STATE_RINGS["MI"]) >= 2  # upper and lower peninsulas
    assert sum(len(ring) for ring in STATE_RINGS["AK"]) >= 80
    assert sum(len(ring) for ring in STATE_RINGS["HI"]) >= 40
    assert len(STATE_RINGS["HI"]) >= 5  # the main islands


def test_dashboard_map_is_large_with_performance_pins(tmp_path, monkeypatch):
    app, window = _boot(tmp_path, monkeypatch)
    window._open_app("home")
    app.processEvents()
    home = window.desktop.home
    store_map = home.findChild(StoreMap)
    assert store_map is not None
    store_map.grab()
    visible = store_map.visibleRegion().boundingRect()
    if not visible.isValid():
        visible = store_map.rect()
    # Visible map (CONUS plus the inset band under it) stays large on the fold.
    assert visible.height() >= 210
    assert store_map.minimumHeight() >= 210
    # The map card should take a substantial share of the dashboard width.
    card = home.findChild(QWidget, "mapCard")
    assert card is not None
    assert card.width() >= 500
    text = _text(home)
    assert "High performer" in text and "On target" in text and "Below target" in text
    assert DASH_PIN_HIGH.lower() == "#22c55e"
    assert DASH_PIN_MID.lower() == "#f5c542"
    assert DASH_PIN_LOW.lower() in {"#ef4444", "#f43f5e", "#dc2626"}
    window.close()


def test_kpi_icons_and_profit_margin_tile(tmp_path, monkeypatch):
    app, window = _boot(tmp_path, monkeypatch)
    window._open_app("home")
    app.processEvents()
    home = window.desktop.home
    text = _text(home)
    assert "TAKE" in text and "DRAWER" in text and "STORE P&L" in text and "SUNDAY" in text
    assert "MARGIN" in text
    icons = home.findChildren(KpiIcon)
    assert len(icons) == 3
    assert {icon.kind for icon in icons} == {"wallet", "bars", "pie"}
    tile = home.findChild(QWidget, "kpiContribution")
    assert tile is not None
    assert tile.height() == 128
    assert any("%" in lab.text() or "MARGIN" in lab.text() for lab in tile.findChildren(QLabel))
    window.close()


def test_revenue_trend_is_a_labeled_line_chart(tmp_path, monkeypatch):
    app, window = _boot(tmp_path, monkeypatch)
    window._open_app("home")
    app.processEvents()
    home = window.desktop.home
    charts = home.findChildren(LineChart)
    assert charts
    chart = charts[0]
    assert home.findChild(QWidget, "revenueCard") is not None
    # The painter is covered by constructing a chart with weeks and grabbing it.
    chart.points = [("Week 1", 1000.0), ("Week 2", 1800.0), ("Week 3", 1400.0), ("Week 4", 2200.0)]
    chart.dark = True
    chart.resize(320, 160)
    pix = chart.grab()
    assert pix.width() >= 200 and pix.height() >= 100
    window.close()


def test_performance_table_has_status_chip_and_deltas(tmp_path, monkeypatch):
    app, window = _boot(tmp_path, monkeypatch)
    window._open_app("home")
    app.processEvents()
    home = window.desktop.home
    card = home.findChild(QWidget, "perfCard")
    assert card is not None
    text = _text(card)
    assert "STATUS" in text
    assert "SHARE OF CHAIN" in text
    assert "MARGIN" in text
    chips = card.findChildren(QLabel, "statusChip")
    dots = card.findChildren(QLabel, "statusDot")
    assert chips and dots
    assert any(label.text() in {"High performer", "On target", "Below target"} for label in chips)
    deltas = card.findChildren(QLabel, "deltaLabel")
    assert deltas
    window.close()


def test_economy_news_strip_is_guarded_with_empty_state(tmp_path, monkeypatch):
    app, window = _boot(tmp_path, monkeypatch)
    window._open_app("home")
    app.processEvents()
    home = window.desktop.home
    strip = home.findChild(QFrame, "economyNews")
    assert strip is not None
    text = _text(strip)
    assert "ECONOMY NEWS" in text
    # A brand-new game may have no items yet; the empty state must still be polite.
    assert "No economy news on the wire." in text or home.findChildren(QLabel, "newsItem")
    window.close()
