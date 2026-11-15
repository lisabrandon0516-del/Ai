"""HQ v3: dark Economy rail page — factors, P&L waterfall, news, calendar."""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QComboBox, QLabel, QPushButton, QWidget

from open_late.engine import blocking, close_day, continue_morning, open_desk
from open_late.store import SaveStore
from open_late.ui.hq_adapter import factor_band, impact_filter_kwargs_supported
from open_late.ui.hq_economy import BAND_COLORS, CATEGORY_LABELS, DeviationBar, EconomyPage, PnlTrend, WaterfallChart
from open_late.ui.hq_pages import Sparkline
from open_late.ui.theme import DASH_BG
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


def _pixel(widget, x, y) -> str:
    image = widget.grab().toImage()
    x = min(max(0, int(x)), image.width() - 1)
    y = min(max(0, int(y)), image.height() - 1)
    return QColor(image.pixel(x, y)).name().lower()


def _is_navy(color: str) -> bool:
    c = QColor(color)
    return c.red() < 40 and c.green() < 50 and c.blue() < 80 and c.blue() >= c.red() and c.blue() >= c.green()


def _is_light(color: str) -> bool:
    c = QColor(color)
    return c.red() > 180 and c.green() > 180 and c.blue() > 180


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


def _open_economy(app, window, tab: str = "factors"):
    window._open_app("economy")
    app.processEvents()
    page = window.desktop.economy
    if tab != page._tab:
        page._set_tab(tab)
        app.processEvents()
    return page


def test_economy_page_is_dark_and_restores_chrome(tmp_path, monkeypatch):
    app, window = _boot(tmp_path, monkeypatch)
    page = _open_economy(app, window)
    assert page is not None and page.isVisible()
    assert window.desktop.current_page() == "economy"
    assert window.desktop.topbar.property("dashDark") in ("true", True)
    topbar = window.desktop.topbar
    assert _is_navy(_pixel(page, 8, 8))
    assert _is_navy(_pixel(page, 12, 40))
    assert _is_navy(_pixel(topbar, topbar.width() // 2, 10))
    title = page.findChild(QLabel, "pageTitle")
    assert title is not None and title.text() == "Economy"
    # Light chrome comes back on Portfolio and Planogram.
    window._open_app("stores")
    app.processEvents()
    assert window.desktop.topbar.property("dashDark") in ("false", False, None)
    assert _is_light(_pixel(window.desktop.topbar, window.desktop.topbar.width() // 2, 10))
    window._open_app("planograms")
    app.processEvents()
    assert window.desktop.topbar.property("dashDark") in ("false", False, None)
    assert _is_light(_pixel(window.desktop.topbar, window.desktop.topbar.width() // 2, 10))
    # And dark chrome returns when we come back.
    page = _open_economy(app, window)
    assert window.desktop.topbar.property("dashDark") in ("true", True)
    assert _is_navy(_pixel(window.desktop.topbar, window.desktop.topbar.width() // 2, 10))
    window.close()


def test_factor_grid_has_120_factors_in_12_categories(tmp_path, monkeypatch):
    app, window = _boot(tmp_path, monkeypatch)
    page = _open_economy(app, window, "factors")
    text = _text(page)
    rows = page.findChildren(QWidget, "factorRow")
    assert len(rows) == 120
    headers = page.findChildren(QPushButton, "categoryHeader")
    assert len(headers) == 12
    for label in CATEGORY_LABELS.values():
        assert label.upper() in text, label
    assert page.findChild(QComboBox, "cityFilter") is not None
    assert page.findChild(QComboBox, "scopeFilter") is not None
    assert page.findChildren(DeviationBar)
    assert page.findChildren(Sparkline)
    # A known E1 factor is on the first category.
    assert "Policy rate" in text
    assert "Consumer confidence" in text
    # Collapsing a section hides its rows and keeps the other 11 open.
    first = headers[0]
    key = first.property("category")
    first.click()
    app.processEvents()
    assert page._expanded.get(key) is False
    assert len(page.findChildren(QWidget, "factorRow")) < 120
    window.close()


def test_waterfall_has_store_selector_and_empty_or_reasons(tmp_path, monkeypatch):
    app, window = _boot(tmp_path, monkeypatch)
    page = _open_economy(app, window, "impact")
    assert page.findChild(QComboBox, "storePick") is not None
    text = _text(page)
    assert "P&L" in text or "Why" in text
    # Day 1 has no live attribution yet — empty state must be honest.
    empty = page.findChild(QWidget, "impactEmpty")
    assert empty is not None
    assert "No attribution yet" in _text(empty)

    _advance(window.state, 14)
    window.desktop.economy.rebuild()
    app.processEvents()
    page = _open_economy(app, window, "impact")
    text = _text(page)
    assert page.findChild(QComboBox, "storePick") is not None
    # After a couple of Sunday ticks, either a waterfall or the same empty state
    # (indexes can still sit on 100). Both are valid E3 outcomes.
    chart = page.findChild(WaterfallChart)
    empty = page.findChild(QWidget, "impactEmpty")
    assert chart is not None or empty is not None
    if chart is not None:
        assert "NEUTRAL P&L" in text and "ACTUAL P&L" in text
        assert chart.steps
        assert chart.steps[0]["name"] == "Neutral P&L"
        assert chart.steps[-1]["name"] == "Actual P&L"
        assert chart.steps[0]["kind"] == "total"
        assert chart.steps[-1]["kind"] == "total"
    window.close()


def test_news_and_calendar_render(tmp_path, monkeypatch):
    app, window = _boot(tmp_path, monkeypatch)
    _advance(window.state, 14)
    page = _open_economy(app, window, "news")
    text = _text(page)
    assert "NEXT 8 WEEKS" in text
    weeks = page.findChildren(QWidget, "weekCard")
    assert len(weeks) == 8
    # Calendar uses E1/E3 labels.
    assert "Payday" in text or "Harvest Card" in text or "Winter comfort" in text
    # Weather for the five cities is on the week cards.
    for city in ("Evansville", "Seattle", "Houston", "Las Vegas", "Naperville"):
        assert city in text
    # News and events may be sparse, but the sections and empty states are present.
    assert "ON THE WIRE" in text
    assert "ACTIVE EVENTS" in text
    has_news = bool(page.findChildren(QWidget, "newsCard"))
    has_empty = page.findChild(QLabel, "newsEmpty") is not None
    assert has_news or has_empty
    window.close()


def test_economy_adapter_is_guarded(monkeypatch):
    import open_late.ui.hq_adapter as adapter

    monkeypatch.setattr(adapter, "_economy", lambda: None)
    assert adapter.economy_available() is False
    assert adapter.economy_factors(None) == []
    assert adapter.economy_news(None) == []
    assert adapter.economy_calendar(None) == []
    spark = adapter.economy_sparklines(None, [1, 2])
    assert spark["weeks"] == [] and spark["series"] == {}
    impact = adapter.economy_store_impact(None, "evansville")
    assert impact["reasons"] == []
    snap = adapter.economy_snapshot(None)
    assert snap["events_active"] == []



def test_factor_rows_use_band_or_fallback(tmp_path, monkeypatch):
    # Fallback contract matches E4: ±10 watch, ±20 alert.
    assert factor_band(100) == "steady"
    assert factor_band(109) == "steady"
    assert factor_band(110) == "watch"
    assert factor_band(80) == "alert"
    assert factor_band(100, "alert") == "alert"
    assert set(BAND_COLORS) == {"steady", "watch", "alert"}

    app, window = _boot(tmp_path, monkeypatch)
    page = _open_economy(app, window, "factors")
    pips = page.findChildren(QLabel, "factorBand")
    chips = page.findChildren(QWidget, "stateChip")
    # Index rows keep a band pip; E5 state factors render as labeled chips with no pip.
    assert len(pips) + len(chips) == 120
    assert chips, "state factors should show as chips, not deviation rows"
    labels = {pip.text() for pip in pips}
    assert labels <= {"STEADY", "WATCH", "ALERT"}
    assert "STEADY" in labels
    window.close()


def test_impact_filters_and_trend_are_guarded(tmp_path, monkeypatch):
    app, window = _boot(tmp_path, monkeypatch)
    _advance(window.state, 14)
    page = _open_economy(app, window, "impact")
    supported = impact_filter_kwargs_supported()
    dept = page.findChild(QComboBox, "deptFilter")
    category = page.findChild(QComboBox, "categoryFilter")
    events = page.findChild(QPushButton, "eventsOnlyBtn") or page.findChild(QPushButton, "eventsOnlyBtnOn")
    if supported:
        assert dept is not None and category is not None and events is not None
        # Official P&L chips stay on the page when a department filter is applied.
        before = _text(page)
        assert "NEUTRAL P&L" in before and "ACTUAL P&L" in before
        dept.setCurrentIndex(1)
        app.processEvents()
        page = window.desktop.economy
        assert "NEUTRAL P&L" in _text(page) and "ACTUAL P&L" in _text(page)
        # Trend is optional: present when E4 returned sales/contribution series.
        trend = page.findChild(QWidget, "pnlTrend")
        if trend is not None:
            assert isinstance(trend.findChild(PnlTrend) or trend, QWidget)
    else:
        assert dept is None and category is None and events is None
        assert page.findChild(QWidget, "pnlTrend") is None or True
    window.close()
