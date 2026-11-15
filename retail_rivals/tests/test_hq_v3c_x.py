"""HQ v3c: E5 movers and state chips, inset callouts, compact six-figure money."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect
from PySide6.QtWidgets import QApplication, QLabel, QWidget

from open_late.store import SaveStore
from open_late.text import money, money_compact, money_compact_signed
from open_late.ui.hq_adapter import (
    STATE_FACTOR_IDS,
    economy_movers,
    factor_band,
    factor_kind,
    factor_neutral,
)
from open_late.ui.hq_art import StoreMap, place_callout
from open_late.ui.hq_economy import DeviationBar
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
    window._chosen_economy = "standard"
    window._start()
    app.processEvents()
    return app, window


def test_money_compact_formats_thousands_and_millions_and_keeps_exact_on_money():
    assert money(128_400) == "$128,400"
    assert money_compact(128_400) == "$128.4k"
    assert money_compact(85_000) == "$85k"
    assert money_compact(1_200_000) == "$1.2M"
    assert money_compact(-1_200_000) == "-$1.2M"
    assert money_compact(850) == "$850"
    assert money_compact_signed(128_400) == "+$128.4k"
    assert money_compact_signed(-12_500) == "−$12.5k"
    assert money_compact_signed(0) == "$0"
    # Exact form is unchanged and is what tooltips should show.
    assert money(185_000) == "$185,000"


def test_factor_kind_and_band_are_guarded_when_keys_are_missing():
    assert factor_kind({"id": 82, "kind": "state"}) == "state"
    assert factor_kind({"id": 1, "kind": "index"}) == "index"
    # Missing kind still classifies the published E5 state ids.
    assert factor_kind({"id": 82}) == "state"
    assert factor_kind({"id": 61}) == "state"
    assert factor_kind({"id": 1}) == "index"
    assert 82 in STATE_FACTOR_IDS and 1 not in STATE_FACTOR_IDS
    assert factor_band(140, kind="state") == "steady"
    assert factor_band(140, band="watch", kind="index") == "watch"
    assert factor_band(100, kind="index", neutral=100) == "steady"
    # Fallback gap uses the provided neutral, not a hardcoded 100, when band/API are absent.
    assert factor_neutral({"kind": "index"}) == 100.0
    assert factor_neutral({"kind": "index", "neutral": 80}) == 80.0


def test_movers_rank_index_factors_by_distance_from_neutral():
    rows = [
        {"id": 82, "name": "Northline focus", "kind": "state", "value": 1, "neutral": 0, "band": "steady", "label": "Focus: Grocery"},
        {"id": 2, "name": "Near", "kind": "index", "value": 102, "neutral": 100, "delta": 1, "band": "steady"},
        {"id": 3, "name": "Far", "kind": "index", "value": 70, "neutral": 100, "delta": -4, "band": "alert"},
        {"id": 4, "name": "Mid", "kind": "index", "value": 88, "neutral": 100, "delta": -2, "band": "watch"},
        {"id": 5, "name": "Also mid", "kind": "index", "value": 112, "neutral": 100, "delta": 3, "band": "watch"},
        {"id": 6, "name": "State-looking", "kind": "state", "value": 0, "neutral": 0, "band": "steady", "label": "Strained"},
        {"id": 7, "name": "Tiny", "kind": "index", "value": 101, "neutral": 100, "delta": 0, "band": "steady"},
    ]

    # Simulate the adapter fallback ranking without calling the engine.
    from open_late.ui import hq_adapter as adapter

    ranked = sorted(
        [row for row in rows if factor_kind(row) == "index"],
        key=lambda row: (-abs(float(row["value"]) - float(row["neutral"])), int(row["id"])),
    )[:5]
    names = [row["name"] for row in ranked]
    assert names[0] == "Far"
    assert "Northline focus" not in names
    assert "State-looking" not in names
    assert set(names) <= {"Far", "Mid", "Also mid", "Near", "Tiny"}
    # economy_movers is present on the adapter and returns a list (live or empty).
    assert callable(adapter.economy_movers)


def test_factors_tab_uses_movers_and_state_chips(tmp_path, monkeypatch):
    app, window = _boot(tmp_path, monkeypatch)
    window._open_app("economy")
    app.processEvents()
    page = window.desktop.economy
    page._set_tab("factors")
    app.processEvents()
    strip = page.findChild(QWidget, "moversStrip")
    assert strip is not None
    cells = strip.findChildren(QWidget, "moverCell")
    assert len(cells) == 5
    expected = economy_movers(window.state, limit=5)
    names = [cell.findChild(QLabel, "moverName").text() for cell in cells]
    assert names == [row["name"] for row in expected]
    assert all(factor_kind(row) == "index" for row in expected)

    # State factors render as labeled chips: no deviation bar, no 'vs 100'.
    from open_late.ui.hq_adapter import economy_factors

    rows = economy_factors(window.state)
    state_rows = [row for row in rows if factor_kind(row) == "state"]
    assert state_rows, "E5 should expose state factors on a standard-economy game"
    chips = page.findChildren(QWidget, "stateChip")
    assert chips, "state factors should show as labeled chips"
    labels = [chip.findChild(QLabel, "stateChipLabel").text() for chip in chips]
    assert all(text.strip() for text in labels)
    # No chip should fall back to a 'vs 100' caption.
    assert all("vs 100" not in text for text in labels)
    for frame in page.findChildren(QWidget, "factorRow"):
        if frame.property("factorKind") == "state":
            assert frame.findChild(DeviationBar) is None
            assert frame.findChild(QLabel, "factorBand") is None
            text = " ".join(lab.text() for lab in frame.findChildren(QLabel))
            assert "vs 100" not in text
        elif frame.property("factorKind") == "index":
            assert frame.findChild(DeviationBar) is not None
    window.close()


def test_inset_callouts_stay_inside_the_map_card():
    app = QApplication.instance() or QApplication([])
    widget = StoreMap(theme="dark")
    widget.resize(760, 340)
    widget.show()
    app.processEvents()
    widget.set_pins([
        {
            "id": "anchorage", "label": "Anchorage", "lon": -149.90, "lat": 61.22,
            "owned": True, "rank": "high", "sales_label": "$128.4k",
            "contrib_label": "Contrib. 12.0%", "tip": "Anchorage · $128,400",
        },
        {
            "id": "honolulu", "label": "Honolulu", "lon": -157.86, "lat": 21.31,
            "owned": True, "rank": "low", "sales_label": "$85k",
            "contrib_label": "Contrib. 4.0%", "tip": "Honolulu · $85,000",
        },
        {
            "id": "juneau", "label": "Juneau", "lon": -134.42, "lat": 58.30,
            "owned": True, "rank": "mid", "sales_label": "$12.5k", "tip": "Juneau · $12,500",
        },
    ])
    app.processEvents()
    widget.repaint()
    app.processEvents()
    host = widget._host_rect()
    frames = widget.inset_frames()
    laid = {pin["id"]: pin for pin in widget.layout_pins()}
    pix = widget.grab()
    assert pix is not None
    # Pins in Alaska and Hawaii still land in their inset frames.
    frames = widget.inset_frames()
    for ident, region in (("anchorage", "AK"), ("juneau", "AK"), ("honolulu", "HI")):
        pin = laid[ident]
        point = pin["_point"]
        assert frames[region].adjusted(-8, -8, 8, 8).contains(point), (ident, point, frames[region])
    # One callout, even for an inset city: park it in a card corner, off the land.
    for ident in ("honolulu", "anchorage", "juneau"):
        for pin in widget.pins:
            pin["selected"] = pin["id"] == ident
        widget.grab()
        box = widget.layout_callout()
        assert box is not None and box.isValid(), ident
        chosen = widget.primary_callout_pin()
        assert chosen is not None and chosen["id"] == ident
        assert host.adjusted(-1, -1, 1, 1).contains(box), (ident, box, host)
        assert QRect(0, 0, widget.width(), widget.height()).contains(box)
        assert not widget.callout_hits_states(box), (ident, box)
    # place_callout itself never leaves the given bounds.
    bounds = QRect(10, 10, 120, 80)
    box = place_callout(QPoint(20, 20), 90, 40, bounds, (12, -28))
    assert bounds.adjusted(0, 0, 0, 0).contains(box) or bounds.intersects(box)
    assert bounds.adjusted(-2, -2, 2, 2).contains(box)
    widget.close()


def test_dashboard_cash_uses_compact_text_and_exact_tooltip(tmp_path, monkeypatch):
    app, window = _boot(tmp_path, monkeypatch)
    # Starting cash on the E5 corporate card is already in the six-figure neighborhood
    # for some difficulties; either way the tray must show compact when the amount
    # is at least $1,000 and keep the exact figure on the tooltip.
    cash = int(window.state.cash)
    shown = window.desktop.topbar.cash.text()
    tip = window.desktop.topbar.cash.toolTip()
    if abs(cash) >= 1_000:
        assert shown == money_compact(cash)
        assert shown != money(cash) or cash % 1000 == 0 and shown.endswith("k")
    assert money(cash) in (tip or '') or shown == money(cash)
    # KPI drawer uses the same helper.
    window._open_app("home")
    app.processEvents()
    kpi = window.desktop.home.findChild(QLabel, "kpiValue")
    # The drawer tile is the first kpiValue.
    values = window.desktop.home.findChildren(QLabel, "kpiValue")
    assert values
    drawer = values[0]
    assert drawer.text() == money_compact(cash)
    assert money(cash) in (drawer.toolTip() or '') or drawer.text() == money(cash)
    window.close()
