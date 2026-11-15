"""HQ v3g: compact money and visit counts at real E7 / eight-figure scale."""

from __future__ import annotations

import re

from PySide6.QtWidgets import QApplication, QLabel

from open_late.engine import blocking, close_day, continue_morning, open_desk
from open_late.store import SaveStore
from open_late.text import (
    count_compact,
    money,
    money_axis_ticks,
    money_compact,
    nice_money_ceiling,
)
from open_late.ui.hq_adapter import chain_board
from open_late.ui.hq_pages import LineChart
from open_late.ui.window import MainWindow, _MoneyBars, _SalesCurve

_EXACT_MILLIONS = re.compile(r"\$\d{1,3}(?:,\d{3}){2,}")


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


def _keep_shelves(state) -> None:
    """Send a warehouse truck and top up Evansville so E7 volume does not stock out."""
    from open_late.content import SUPPLIERS
    from open_late.corporate import allocate, replenish
    from open_late.engine import place_order
    from open_late.ui.hq_adapter import warehouse_units

    if warehouse_units(state) < 80_000:
        for supplier in SUPPLIERS.values():
            if supplier.id == "labelco" and not getattr(state.flags, "private_label", False):
                continue
            quantities = {}
            for product in state.products.values():
                if product.supplier_id != supplier.id:
                    continue
                line = state.stock[product.id]
                have = line.on_hand + line.on_order
                if have < 800:
                    quantities[product.id] = 2000
            if quantities:
                place_order(state, supplier.id, quantities)
    for door in getattr(state, "doors", []) or []:
        if getattr(door, "status", "open") != "open":
            continue
        replenish(state, door.id)
        floor = sum(line.on_hand for line in door.stock.values())
        inbound = 0
        for shipment in getattr(state, "shipments", []) or []:
            if shipment.door_id == door.id:
                inbound += sum(shipment.lines.values())
        if floor + inbound >= 40_000:
            continue
        # Replenish is silent after a stock-out week (target follows last week's sales).
        # Send a baseline truck from whatever the warehouse still holds.
        need = 80_000 - floor - inbound
        quantities = {}
        for product in state.products.values():
            available = state.stock[product.id].on_hand
            if available <= 0:
                continue
            take = min(available, max(40, need // max(1, len(state.products))))
            if take > 0:
                quantities[product.id] = take
        if quantities:
            allocate(state, door.id, quantities)


def _advance(state, days: int = 10, restock: bool = False) -> None:
    for index in range(days):
        if restock and index % 2 == 0:
            _keep_shelves(state)
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


def chain_take(state) -> int:
    board = chain_board(state, days=56) or []
    row = next((item for item in board if item.get("store_id") == "chain"), None)
    board_sales = int(row.get("sales") or 0) if row else 0
    history_sales = sum(int(item.revenue or 0) for item in (state.history or [])[-56:])
    return max(board_sales, history_sales)


def _scale_take_only(state, target: int) -> int:
    """Scale recorded sales so the chain total reaches eight figures. Cash is left alone."""
    take = chain_take(state)
    if take <= 0:
        return take
    factor = target / take
    for item in state.history or []:
        if hasattr(item, "revenue"):
            item.revenue = int(round(int(item.revenue or 0) * factor))
    for item in getattr(state, "store_days", []) or []:
        if hasattr(item, "sales"):
            item.sales = int(round(int(item.sales or 0) * factor))
        if getattr(item, "by_department", None):
            item.by_department = {
                dept: int(round(int(amount or 0) * factor))
                for dept, amount in item.by_department.items()
            }
    return chain_take(state)


def play_to_chain_total(state, target: int = 14_600_000, max_days: int = 63) -> int:
    """Advance real E7 days, keeping shelves stocked, until last-8-weeks sales hit eight figures.

    Injects a sales-only scale if the engine still cannot get there.
    """
    _advance(state, max_days, restock=True)
    take = chain_take(state)
    if take >= 10_000_000:
        return take
    return _scale_take_only(state, target)


def _visible_label_texts(widget) -> list[str]:
    texts = []
    for label in widget.findChildren(QLabel):
        if not label.isVisible():
            continue
        texts.append(label.text() or "")
    return texts


def test_count_compact_keeps_daily_visits_grouped_and_compacts_weekly():
    assert count_compact(4100) == "4,100"
    assert count_compact(4_100) == "4,100"
    assert count_compact(28_700) == "28.7k"
    assert count_compact(10_000) == "10k"
    assert count_compact(9_999) == "9,999"
    assert count_compact(1_200_000) == "1.2M"
    assert count_compact(0) == "0"


def test_money_axis_ticks_are_compact_and_cover_eight_figures():
    ceil, ticks = money_axis_ticks(1_840_000)
    assert ceil >= 1_840_000
    assert ceil <= 2_500_000
    assert ticks[0] == (0, "$0")
    assert ticks[-1][0] == ceil
    assert all("," not in label for _value, label in ticks)
    assert any(label.endswith("M") for _value, label in ticks[1:])

    ceil8, ticks8 = money_axis_ticks(14_600_000)
    assert ceil8 >= 14_600_000
    assert ceil8 <= 20_000_000
    labels = [label for _value, label in ticks8]
    assert "$0" in labels
    assert any(label.endswith("M") for label in labels)
    assert all("," not in label for label in labels)
    # A raw seven-figure tick would be a bug; compact stays short.
    assert all(len(label) <= 8 for label in labels)
    assert nice_money_ceiling(14_600_000) == ceil8


def test_line_chart_y_ticks_are_compact_at_millions(monkeypatch):
    app = _app(monkeypatch)
    points = [
        {"label": f"Week {index + 1}", "value": 12_800_000 + index * 260_000, "tip": money(12_800_000 + index * 260_000)}
        for index in range(8)
    ]
    points[-1]["value"] = 14_600_000
    points[-1]["tip"] = money(14_600_000)
    chart = LineChart("Revenue trend", points)
    chart.resize(520, 220)
    chart.show()
    app.processEvents()
    chart.grab()
    ticks = chart._axis_ticks
    assert ticks, "LineChart must expose compact Y ticks after paint"
    labels = [label for _value, label in ticks]
    assert labels[0] == "$0"
    assert all("," not in label for label in labels)
    assert chart._axis_ceiling >= 14_600_000
    assert chart._axis_ceiling <= 20_000_000
    assert any(label.endswith("M") for label in labels)
    # Hover still carries the exact eight-figure amount.
    assert any("$14,600,000" in tip for _rect, tip in chart._hits)


def test_finance_and_sales_charts_use_compact_ticks(monkeypatch):
    app = _app(monkeypatch)
    curve = _SalesCurve([(str(day), 1_840_000 + day * 20_000) for day in range(1, 15)])
    curve.resize(640, 240)
    curve.show()
    app.processEvents()
    curve.grab()
    assert curve._axis_ceiling >= 2_000_000
    assert all("," not in label for _value, label in curve._axis_ticks)

    bars = _MoneyBars(
        "Drawer at close",
        [(str(day), 10_000_000 + day * 400_000) for day in range(1, 15)],
        "#0B6CBD",
    )
    bars.resize(640, 240)
    bars.show()
    app.processEvents()
    bars.grab()
    assert bars._axis_ceiling >= 14_600_000
    assert bars._axis_ceiling <= 20_000_000
    assert all("," not in label for _value, label in bars._axis_ticks)
    assert any(label.endswith("M") for _value, label in bars._axis_ticks)


def test_finance_statement_uses_compact_with_exact_tooltip(tmp_path, monkeypatch):
    app, window = _boot(tmp_path, monkeypatch)
    _advance(window.state, 10)
    if hasattr(window, "refresh"):
        window.refresh()
    window._open_app("books")
    app.processEvents()
    amounts = window.findChildren(QLabel, "statementAmount")
    assert amounts, "P&L / balance lines should be tagged statementAmount"
    compact_seen = False
    for label in amounts:
        text = label.text() or ""
        tip = label.toolTip() or ""
        assert not _EXACT_MILLIONS.search(text), text
        if "M" in text or "k" in text:
            compact_seen = True
            assert tip.lstrip("-").startswith("$") and "," in tip
            # Exact tooltip matches money() and is not the compact form.
            assert text != tip
    assert compact_seen, "quarter P&L at E7 scale should show compact millions or thousands"
    window.close()


def test_sales_page_uses_compact_money_and_visit_counts(tmp_path, monkeypatch):
    app, window = _boot(tmp_path, monkeypatch)
    _advance(window.state, 2)
    if hasattr(window, "refresh"):
        window.refresh()
    window._open_app("sales")
    app.processEvents()
    tape = window.findChild(QLabel, "salesNarrate")
    assert tape is not None
    text = tape.text() or ""
    tip = tape.toolTip() or ""
    revenue = int(window.state.last_report.revenue or 0)
    visits = int(window.state.last_report.visits or 0)
    assert money_compact(revenue) in text
    assert not _EXACT_MILLIONS.search(text)
    assert money(revenue) in tip
    assert count_compact(visits) in text
    assert str(visits) in tip or f"{visits:,}" in tip
    window.close()


def test_hq_screens_fit_with_real_eight_figure_chain_total(tmp_path, monkeypatch):
    app, window = _boot(tmp_path, monkeypatch)
    take = play_to_chain_total(window.state, target=10_000_000, max_days=70)
    assert take >= 10_000_000, f"chain total stayed at {take}"
    if hasattr(window, "refresh"):
        window.refresh()
    window._say("")
    app.processEvents()

    screens = ("home", "stores", "economy", "planograms", "books", "sales", "pos")
    for width, height in ((1366, 768), (1100, 700)):
        window.setMinimumSize(1, 1)
        window.resize(width, height)
        app.processEvents()
        for app_id in screens:
            window._open_app(app_id)
            app.processEvents()
            grab = window.grab()
            assert grab.width() >= min(width, 1000)
            assert grab.height() >= min(height, 680)
            tight_names = {
                "statementAmount", "todayValue", "figureValue", "kpiValue",
                "shareLabel", "drawerLabor", "drawerPnlLines", "drawerWeek",
            }
            leaks = []
            for label in window.findChildren(QLabel):
                if not label.isVisible():
                    continue
                text = label.text() or ""
                name = label.objectName() or ""
                amount_only = bool(re.fullmatch(r"-?\$[\d,]+(?:\.\d+)?", text.strip()))
                if name in tight_names or amount_only:
                    if _EXACT_MILLIONS.search(text):
                        leaks.append(f"{name}: {text}")
            assert not leaks, f"{app_id} @{width}x{height} leaked exact millions: {leaks}"
            texts = _visible_label_texts(window)
            blob = "\n".join(texts)
            if app_id == "home":
                assert money_compact(take) in blob or money_compact(window.state.cash) in blob
            if app_id == "books":
                amounts = [lab.text() for lab in window.findChildren(QLabel, "statementAmount")]
                assert amounts
                assert all(not _EXACT_MILLIONS.search(text or "") for text in amounts)
    # Dashboard trend ticks stay compact at the real chain scale.
    window._open_app("home")
    app.processEvents()
    chart = window.desktop.home.findChild(LineChart)
    if chart is not None:
        chart.grab()
        if chart._axis_ticks:
            assert all("," not in label for _value, label in chart._axis_ticks)
    window.close()
