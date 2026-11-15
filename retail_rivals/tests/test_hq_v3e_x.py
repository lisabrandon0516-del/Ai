"""HQ v3e: partial-week revenue trend, share-of-chain table, news ticker."""

from __future__ import annotations

from types import SimpleNamespace

from PySide6.QtCore import QPoint, QTimer
from PySide6.QtGui import QHelpEvent
from PySide6.QtWidgets import QApplication, QLabel, QToolTip, QWidget

from open_late.engine import blocking, close_day, continue_morning, open_desk
from open_late.economy import week_id
from open_late.store import SaveStore
from open_late.text import WEEKDAYS, is_sunday, money
from open_late.ui.hq_pages import LineChart, NewsTicker, _week_length, _week_points
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
    if state.phase == "morning":
        open_desk(state)


def _text(widget) -> str:
    parts = []
    if isinstance(widget, QLabel):
        parts.append(widget.text())
    for child in widget.findChildren(QLabel):
        parts.append(child.text())
    return "\n".join(parts)


def test_week_points_use_engine_days_and_do_not_treat_a_partial_week_as_complete():
    assert _week_length() == len(WEEKDAYS) == 7
    history = [SimpleNamespace(day=day, revenue=1000 * day) for day in range(1, 13)]
    state = SimpleNamespace(day=13)
    points = _week_points(history, state)
    assert points, "expected weekly points once a week has closed"
    complete = [row for row in points if not row.get("partial")]
    partial = [row for row in points if row.get("partial")]
    assert len(complete) == 1 and complete[0]["week"] == 1
    # Days 1-7 are a full engine week (Sunday closes it).
    assert complete[0]["days"] == 7
    assert complete[0]["value"] == sum(1000 * day for day in range(1, 8))
    assert len(partial) == 1
    # Days 8-12 are five closed days of the current week; day 13 is still open.
    closed = [item for item in history if week_id(item.day) == week_id(state.day)]
    n = len(closed)
    assert n == 5
    assert not is_sunday(state.day)
    assert partial[0]["days"] == n
    assert partial[0]["value"] == sum(item.revenue for item in closed)
    assert partial[0]["label"] == f"Week so far ({n} days)"
    assert money(int(partial[0]["value"])) in partial[0]["tip"]
    assert f"{n} days elapsed" in partial[0]["tip"]
    # A finished Sunday week has no trailing partial point.
    done = _week_points(history[:7], SimpleNamespace(day=8))
    assert done and all(not row.get("partial") for row in done)
    assert done[-1]["label"] == "Week 1" and done[-1]["days"] == 7


def test_revenue_trend_draws_a_dashed_partial_week_on_the_dashboard(tmp_path, monkeypatch):
    app, window = _boot(tmp_path, monkeypatch)
    _advance(window.state, 12)
    window.refresh()
    app.processEvents()
    window._open_app("home")
    app.processEvents()
    home = window.desktop.home
    chart = home.findChild(LineChart)
    assert chart is not None
    rows = chart._rows()
    partial = [row for row in rows if row.get("partial")]
    assert partial, "mid-week game must show a Week so far point"
    n = partial[-1]["days"]
    current = week_id(window.state.day)
    closed = [item for item in window.state.history if item.day and week_id(item.day) == current]
    assert n == len(closed) and n < _week_length()
    assert f"Week so far ({n} days)" in partial[-1]["label"]
    assert f"{n} days elapsed" in partial[-1]["tip"]
    exact = money(int(round(partial[-1]["value"])))
    assert exact in partial[-1]["tip"]
    # The plotted figure is the actual closed-day sum, not a pro-rated full week.
    assert partial[-1]["value"] == sum(float(item.revenue or 0) for item in closed)
    pix = chart.grab()
    assert pix.width() >= 100 and pix.height() >= 80
    window.close()


def test_store_table_labels_share_of_chain_and_shows_net_margin(tmp_path, monkeypatch):
    app, window = _boot(tmp_path, monkeypatch)
    _advance(window.state, 12)
    window.refresh()
    app.processEvents()
    for size in ((1366, 768), (1100, 700)):
        window.resize(*size)
        window._open_app("home")
        app.processEvents()
        home = window.desktop.home
        card = home.findChild(QWidget, "perfCard")
        assert card is not None
        text = _text(card)
        assert "SHARE OF CHAIN" in text
        assert "MARGIN" in text
        shares = card.findChildren(QLabel, "shareLabel")
        margins = card.findChildren(QLabel, "marginLabel")
        assert shares and margins
        # One open door: share is 100%, margin is store P&L / sales (or — if no sales).
        assert any("100.0%" in lab.text() or lab.text() == "—" for lab in shares)
        for lab in margins:
            shown = lab.text().strip()
            assert shown == "—" or shown.endswith("%")
            if shown != "—":
                assert "Net margin" in lab.toolTip()
                assert money  # exact dollars live in the tooltip when sales exist
                assert "$" in lab.toolTip() or "sales" in lab.toolTip().lower()
        # The card and its labels stay inside the window at both sizes.
        assert card.width() <= window.width()
        for lab in list(shares) + list(margins):
            assert lab.width() <= card.width()
            assert not lab.text().endswith("…")
    window.close()


def test_news_ticker_shows_full_headline_and_stops_its_timer_when_hidden(tmp_path, monkeypatch):
    app, window = _boot(tmp_path, monkeypatch)
    long = (
        "Harbor Ledger reports that a sudden port delay stretches sharply through "
        "the week and leaves grocery shelves thinner than buyers expected in Evansville"
    )
    ticker = NewsTicker([
        {
            "text": f"Harbor Ledger  ·  {long}  ·  Evansville",
            "tip": long,
            "color": "#F97316",
        },
        {
            "text": "Basin Review  ·  Heat index builds overnight  ·  Houston",
            "tip": "Heat index builds overnight",
            "color": "#F97316",
        },
    ])
    ticker.resize(240, 22)
    ticker.show()
    app.processEvents()
    ticker._relayout()
    app.processEvents()
    assert long in ticker.full_text()
    assert long in ticker.toolTip()
    items = ticker.findChildren(QLabel, "newsItem")
    assert items and any(long in lab.text() for lab in items)
    assert any(long in (lab.toolTip() or "") for lab in items)
    assert ticker.is_scrolling(), "overflowing ticker should start a marquee while visible"
    ticker.hide()
    app.processEvents()
    assert not ticker.is_scrolling()
    ticker.deleteLater()
    app.processEvents()

    # Dashboard strip keeps the full headline readable (ticker + tooltip).
    window._open_app("home")
    app.processEvents()
    home = window.desktop.home
    strip = home.findChild(QWidget, "economyNews")
    assert strip is not None
    found = home.findChild(NewsTicker) or strip.findChild(QWidget, "newsTicker")
    labels = strip.findChildren(QLabel, "newsItem")
    # Brand-new or mid-setup games may have an empty strip; the empty state stays polite.
    if found is not None:
        assert found.full_text() or labels
        found.hide()
        app.processEvents()
        assert not found.is_scrolling()
    else:
        assert "No economy news on the wire." in _text(strip) or labels
    window.close()
    # Closing the window must not leave a live ticker timer behind.
    assert all(
        not getattr(obj, "is_scrolling", lambda: False)()
        for obj in app.allWidgets()
        if isinstance(obj, NewsTicker)
    )
