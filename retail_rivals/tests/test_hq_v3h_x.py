"""HQ v3h: finance chart above the fold, Sunday KPI sub-row, ticker edge fade."""

from __future__ import annotations

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QLabel, QWidget

from open_late.store import SaveStore
from open_late.text import money, money_compact
from open_late.ui.hq_pages import NewsTicker, _TickerEdgeFade
from open_late.ui.theme import DASH_CARD
from open_late.ui.window import MainWindow, _MoneyBars
from tests.test_hq_v3g_x import _advance


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


def _resize(window, app, size):
    width, height = size
    window.setMinimumSize(1, 1)
    window.resize(width, height)
    app.processEvents()
    window.resize(width, height)
    app.processEvents()


def _color_close(color: QColor, ref: QColor, tol: int = 48) -> bool:
    return (
        abs(color.red() - ref.red()) <= tol
        and abs(color.green() - ref.green()) <= tol
        and abs(color.blue() - ref.blue()) <= tol
    )


def test_finance_cash_chart_fits_above_the_fold_at_both_sizes(tmp_path, monkeypatch):
    app, window = _boot(tmp_path, monkeypatch)
    # Mid-game so closed quarters exist and the page is as tall as a real E7 run.
    _advance(window.state, 32, restock=True)
    if hasattr(window, "refresh"):
        window.refresh()
    app.processEvents()
    for width, height in ((1366, 768), (1100, 700)):
        _resize(window, app, (width, height))
        window._open_app("books")
        app.processEvents()
        chart = window.findChild(_MoneyBars) or window.findChild(QWidget, "moneyBars")
        assert chart is not None, "Drawer at close chart should be on Finance"
        assert chart.isVisible()
        # The $0 tick and day labels live in the bottom ~32px of the widget.
        top = chart.mapTo(window, chart.rect().topLeft())
        bottom = top.y() + chart.height()
        assert top.y() >= 0, f"chart starts offscreen at {width}x{height}: y={top.y()}"
        assert bottom <= height, (
            f"chart bottom {bottom} is below the fold at {width}x{height} "
            f"(top={top.y()} h={chart.height()})"
        )
        # Day labels and the $0 tick must be inside the painted widget, not clipped by height.
        assert chart.height() >= 160
        assert getattr(chart, "_axis_ticks", None)
        assert any(label == "$0" or value == 0 for value, label in chart._axis_ticks)
    window.close()


def test_drawer_kpi_puts_sunday_on_its_own_line(tmp_path, monkeypatch):
    app, window = _boot(tmp_path, monkeypatch)
    _advance(window.state, 2)
    if hasattr(window, "refresh"):
        window.refresh()
    window._open_app("home")
    app.processEvents()
    from open_late.finance import weekly_obligations

    sunday = weekly_obligations(window.state)
    home = window.desktop.home
    drawer = home.findChild(QWidget, "kpiDrawer")
    assert drawer is not None
    line = drawer.findChild(QLabel, "kpiSundayLine")
    assert line is not None, "SUNDAY should live on its own sub-row"
    assert "SUNDAY" in (line.text() or "")
    assert money_compact(sunday) in (line.text() or "")
    assert money(sunday) in (line.toolTip() or "")
    # The delta line next to the cash figure must not also carry SUNDAY.
    deltas = drawer.findChildren(QLabel, "kpiDelta")
    assert deltas
    assert all("SUNDAY" not in (lab.text() or "") for lab in deltas)
    for width, height in ((1366, 768), (1100, 700)):
        _resize(window, app, (width, height))
        window._open_app("home")
        app.processEvents()
        line = window.desktop.home.findChild(QLabel, "kpiSundayLine")
        assert line is not None and line.isVisible()
        assert line.width() <= drawer.width() or line.width() <= window.desktop.home.findChild(QWidget, "kpiDrawer").width()
        # The Sunday row should not overflow its card.
        card = window.desktop.home.findChild(QWidget, "kpiDrawer")
        line_bottom = line.mapTo(card, line.rect().bottomLeft()).y()
        assert line_bottom <= card.height(), f"Sunday line clipped in the card at {width}x{height}"
    window.close()


def test_news_ticker_paints_soft_edge_fade(monkeypatch):
    app = _app(monkeypatch)
    long = (
        "Harbor Ledger reports that a sudden port delay stretches sharply through "
        "the week and leaves grocery shelves thinner than buyers expected in Evansville"
    )
    ticker = NewsTicker([
        {"text": f"Harbor Ledger  ·  {long}  ·  Evansville", "tip": long, "color": "#F8FAFC"},
        {"text": "Basin Review  ·  Heat index builds overnight  ·  Houston", "tip": "Heat", "color": "#F8FAFC"},
    ])
    ticker.resize(280, 22)
    ticker.show()
    app.processEvents()
    ticker._relayout()
    app.processEvents()
    fade = ticker.findChild(_TickerEdgeFade) or ticker.findChild(QWidget, "tickerFade")
    assert fade is not None, "ticker should host a soft edge fade"
    assert fade.width() == ticker.width()
    pix = ticker.grab()
    image = pix.toImage()
    assert image.width() >= 200 and image.height() >= 16
    mid_y = image.height() // 2
    card = QColor(DASH_CARD)
    left = QColor(image.pixel(1, mid_y))
    right = QColor(image.pixel(image.width() - 2, mid_y))
    assert _color_close(left, card), f"left edge {left.name()} should fade into {card.name()}"
    assert _color_close(right, card), f"right edge {right.name()} should fade into {card.name()}"
    ticker.hide()
    app.processEvents()
    assert not ticker.is_scrolling()
    ticker.deleteLater()
    app.processEvents()
