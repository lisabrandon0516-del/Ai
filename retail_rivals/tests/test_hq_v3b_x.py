"""HQ v3b: unclipped rail, calm waterfall scale, biggest-movers strip."""

from __future__ import annotations

from PySide6.QtCore import QRect
from PySide6.QtWidgets import QApplication, QAbstractScrollArea, QLabel, QPushButton, QWidget

from open_late.engine import blocking, close_day, continue_morning, open_desk
from open_late.store import SaveStore
from open_late.ui.hq_economy import WaterfallChart, movement_is_calm
from open_late.ui.hq_shell import RAIL_ITEMS
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
    window._chosen_economy = "standard"
    window._start()
    app.processEvents()
    return app, window


def _text(widget) -> str:
    parts = []
    if isinstance(widget, (QLabel, QPushButton)):
        parts.append(widget.text())
    for child in widget.findChildren(QLabel) + widget.findChildren(QPushButton):
        parts.append(child.text())
    return "\n".join(parts).replace("&&", "&")


def _advance(state, days: int = 10) -> None:
    for _ in range(days):
        if state.phase == "morning":
            open_desk(state)
        if state.phase == "desk":
            for message in list(blocking(state)):
                message.resolved = True
            text = close_day(state)
            if text:
                break
        if state.phase == "evening":
            continue_morning(state)


def _visible_in(widget, ancestor) -> bool:
    if widget is None or not widget.isVisible():
        return False
    top = widget.mapTo(ancestor, widget.rect().topLeft())
    bottom = widget.mapTo(ancestor, widget.rect().bottomRight())
    bounds = ancestor.rect()
    return bounds.contains(top) and bounds.contains(bottom)


def _rail_has_no_scroll(rail) -> bool:
    for scroll in rail.findChildren(QAbstractScrollArea):
        bar = scroll.verticalScrollBar()
        if bar is not None and bar.isVisible() and bar.maximum() > 0:
            return False
    return True


def test_rail_fits_every_entry_without_scrolling(tmp_path, monkeypatch):
    app, window = _boot(tmp_path, monkeypatch)
    window._open_app("home")
    app.processEvents()
    for width, height in ((1366, 768), (1100, 700)):
        window.setMinimumSize(width, height)
        window.setMaximumSize(width, height)
        window.resize(width, height)
        window.desktop.layout_chrome()
        app.processEvents()
        rail = window.desktop.rail
        assert _rail_has_no_scroll(rail), (width, height)
        assert rail.height() <= height
        for app_id, label, _icon, _index in RAIL_ITEMS:
            btn = rail.buttons[app_id]
            assert _visible_in(btn, rail), (width, height, app_id, label)
            # Reachable: the button has a clickable rect inside the rail.
            assert btn.rect().isValid() and btn.isEnabled()
        for name in ("Help", "Save", "Front door"):
            btn = rail.quiet_buttons[name]
            assert _visible_in(btn, rail), (width, height, name)
            assert btn.isEnabled()
            assert btn.toolTip() == name
        # POS is the last nav entry and must not be clipped.
        pos = rail.buttons["pos"]
        assert _visible_in(pos, rail)
        assert pos.rect().height() >= 20
    window.close()


def test_movement_is_calm_is_relative_not_a_fixed_dollar():
    assert movement_is_calm(10_000, 50) is True
    assert movement_is_calm(10_000, 200) is False
    assert movement_is_calm(-4_000, -20) is True
    assert movement_is_calm(-4_000, -80) is False
    assert movement_is_calm(0, 0) is False
    # A large move on a large base can still be calm; a small move on a tiny base may not.
    assert movement_is_calm(1_000_000, 5_000) is True
    assert movement_is_calm(100, 2) is False


def test_calm_waterfall_scales_reason_bars_and_keeps_truthful_labels():
    # Synthetic steps: totals dwarf the reasons, the way a calm week looks.
    # Magnitudes are local to this test, not engine constants.
    base, actual = -80_000, -80_120
    steps = [
        {"name": "Neutral P&L", "kind": "total", "level": base, "prior": 0, "display": "NEUTRAL-LABEL"},
        {"name": "Reason A", "kind": "step", "level": base - 80, "prior": base, "display": "REASON-A"},
        {"name": "Reason B", "kind": "step", "level": actual, "prior": base - 80, "display": "REASON-B"},
        {"name": "Actual P&L", "kind": "total", "level": actual, "prior": 0, "display": "ACTUAL-LABEL"},
    ]
    assert movement_is_calm(base, actual - base)
    calm = WaterfallChart(steps, calm=True)
    calm.resize(800, 240)
    normal = WaterfallChart(steps, calm=False)
    normal.resize(800, 240)
    calm_bars = {row["name"]: row for row in calm.layout_bars(800, 240)}
    normal_bars = {row["name"]: row for row in normal.layout_bars(800, 240)}
    assert calm_bars["Reason A"]["h"] >= 16
    assert calm_bars["Reason B"]["h"] >= 16
    # Relative scale: the larger reason is at least as tall as the smaller one.
    assert calm_bars["Reason A"]["h"] >= calm_bars["Reason B"]["h"]
    # On a true-to-zero axis the reason bars would be hairlines next to the totals.
    assert normal_bars["Reason A"]["h"] < 12
    assert calm_bars["Reason A"]["h"] > normal_bars["Reason A"]["h"] * 2
    # Dollar labels stay the ones we handed in, not a scaled rewrite.
    assert calm_bars["Neutral P&L"]["display"] == "NEUTRAL-LABEL"
    assert calm_bars["Actual P&L"]["display"] == "ACTUAL-LABEL"
    assert calm_bars["Reason A"]["display"] == "REASON-A"
    assert calm_bars["Neutral P&L"]["capped"] is True
    assert calm_bars["Reason A"]["capped"] is False


def test_factors_tab_has_biggest_movers_strip(tmp_path, monkeypatch):
    app, window = _boot(tmp_path, monkeypatch)
    window._open_app("economy")
    app.processEvents()
    page = window.desktop.economy
    page._set_tab("factors")
    app.processEvents()
    strip = page.findChild(QWidget, "moversStrip")
    assert strip is not None
    assert "BIGGEST MOVERS THIS WEEK" in _text(strip)
    cells = strip.findChildren(QWidget, "moverCell")
    assert len(cells) == 5
    for cell in cells:
        assert cell.findChild(QLabel, "moverName") is not None
        assert cell.findChild(QLabel, "moverValue") is not None
        assert cell.findChild(QLabel, "moverDelta") is not None
        band = cell.findChild(QLabel, "moverBand")
        assert band is not None
        assert band.text() in {"STEADY", "WATCH", "ALERT"}
    # The strip ranks index factors by |value - neutral|, not state factors or raw vs-100.
    from open_late.ui.hq_adapter import economy_movers

    expected = economy_movers(window.state, limit=5)
    names = [cell.findChild(QLabel, "moverName").text() for cell in cells]
    assert names == [row["name"] for row in expected]
    assert all((row.get("kind") or "index") == "index" for row in expected)
    window.close()


def test_calm_note_appears_when_movement_is_relative_small(tmp_path, monkeypatch):
    app, window = _boot(tmp_path, monkeypatch)
    _advance(window.state, 16)
    window._open_app("economy")
    app.processEvents()
    page = window.desktop.economy
    page._set_tab("impact")
    app.processEvents()
    from open_late.ui.hq_adapter import economy_store_impact, store_ids

    ids = store_ids(window.state)
    impact = economy_store_impact(window.state, ids[0], days=7)
    pnl = impact.get("pnl") or {}
    neutral = impact.get("neutral_pnl") or {}
    delta = impact.get("delta") or {}
    actual = int(pnl.get("contribution") or 0)
    base = int(neutral.get("contribution") or 0)
    move = int(delta.get("contribution") if delta.get("contribution") is not None else actual - base)
    note = page.findChild(QLabel, "calmNote")
    chart = page.findChild(WaterfallChart)
    if movement_is_calm(base, move):
        assert note is not None
        assert "Economy is calm this week" in note.text()
        assert chart is not None and chart.calm is True
    else:
        # A lively week is a valid E5 outcome; the note must stay off.
        assert note is None
        assert chart is None or chart.calm is False
    window.close()
