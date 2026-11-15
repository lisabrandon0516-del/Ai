"""HQ v3f: compact money at the million scale, and a seven-figure fit check."""

from __future__ import annotations

from PySide6.QtCore import QRect, Qt
from PySide6.QtWidgets import QApplication, QLabel, QWidget

from open_late.engine import blocking, close_day, continue_morning, open_desk
from open_late.economy import week_id
from open_late.store import SaveStore
from open_late.text import money, money_compact, money_compact_signed
from open_late.ui.hq_pages import LineChart
from open_late.ui.window import MainWindow

TARGET_CASH = 12_600_000
TARGET_WEEK = 1_840_000
TARGET_MOVE = -1_200_000

_MONEY_KEYS = (
    "sales", "cogs", "labor", "rent", "freight", "shrink",
    "card_fees", "pos_fees", "contribution", "revenue", "cash_end",
)


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


def _scale_int(value, factor: float) -> int:
    try:
        return int(round(float(value or 0) * factor))
    except (TypeError, ValueError):
        return 0


def _week_revenue(state, wid: int) -> int:
    total = 0
    for item in state.history or []:
        try:
            day = int(item.day or 0)
        except (TypeError, ValueError):
            continue
        if day and week_id(day) == wid:
            total += int(item.revenue or 0)
    return total


def scale_state_to_supercenter(state, *, cash: int = TARGET_CASH, week: int = TARGET_WEEK) -> None:
    """Mutate HQ-visible state dollars to E7-like millions. Does not change the engine."""
    # Use the first completed engine week as the week-scale source.
    source = 0
    for wid in range(0, 8):
        source = _week_revenue(state, wid)
        if source:
            break
    if not source:
        source = sum(int(item.revenue or 0) for item in (state.history or [])[:7]) or 1
    factor = week / source

    state.cash = int(cash)
    report = getattr(state, "last_report", None)
    if report is not None:
        for key in ("revenue", "cogs", "refunds", "rent_paid", "payroll_paid"):
            if hasattr(report, key):
                setattr(report, key, _scale_int(getattr(report, key), factor))
    last_cash = 0
    for item in state.history or []:
        if hasattr(item, "revenue"):
            item.revenue = _scale_int(item.revenue, factor)
        last_cash = int(getattr(item, "cash_end", 0) or last_cash)
    cash_factor = cash / last_cash if last_cash else factor
    running = 0
    for item in state.history or []:
        if hasattr(item, "cash_end"):
            item.cash_end = _scale_int(item.cash_end, cash_factor)
            running = item.cash_end
    if not running:
        pass
    for item in getattr(state, "store_days", []) or []:
        for key in ("sales", "cogs", "labor", "rent", "freight", "shrink", "card_fees", "pos_fees"):
            if hasattr(item, key):
                setattr(item, key, _scale_int(getattr(item, key), factor))
        if getattr(item, "by_department", None):
            item.by_department = {dept: _scale_int(amount, factor) for dept, amount in item.by_department.items()}
    for door in getattr(state, "doors", []) or []:
        for key in ("last_sales", "last_contribution", "labor_budget", "week_sales", "last_week_sales", "rent_weekly"):
            if hasattr(door, key):
                setattr(door, key, _scale_int(getattr(door, key), factor))


def _scale_impact(data, *, week: int = TARGET_WEEK, move: int = TARGET_MOVE) -> dict:
    data = dict(data or {})
    pnl = dict(data.get("pnl") or {})
    neutral = dict(data.get("neutral_pnl") or {})
    delta = dict(data.get("delta") or {})
    actual = int(pnl.get("contribution") or 0)
    base = int(neutral.get("contribution") or 0)
    current_move = int(delta["contribution"]) if delta.get("contribution") is not None else actual - base
    if abs(base) >= 500_000 or abs(actual) >= 500_000:
        return data
    new_base = int(week)
    new_move = int(move)
    new_actual = new_base + new_move
    reasons = []
    raw = list(data.get("reasons") or [])
    total = sum(int(row.get("dollars") or 0) for row in raw) or (len(raw) or 1)
    leftover = new_move
    if raw:
        for index, row in enumerate(raw):
            row = dict(row)
            if index == len(raw) - 1:
                row["dollars"] = leftover
            else:
                row["dollars"] = int(round(int(row.get("dollars") or 0) / total * new_move))
                leftover -= int(row["dollars"])
            reasons.append(row)
    else:
        reasons = [
            {"name": "City traffic baseline", "dollars": -800_000, "line": "sales"},
            {"name": "Northline price index", "dollars": -400_000, "line": "sales"},
        ]
    # Keep sales on the same scale as the week figure when the engine value is still mid-five-figures.
    if int(pnl.get("sales") or 0) < 500_000:
        pnl["sales"] = new_base
    if int(neutral.get("sales") or 0) < 500_000:
        neutral["sales"] = new_base
    pnl["contribution"] = new_actual
    neutral["contribution"] = new_base
    delta["contribution"] = new_move
    data["pnl"] = pnl
    data["neutral_pnl"] = neutral
    data["delta"] = delta
    data["reasons"] = reasons
    return data


def _scale_spark_payload(payload, factor: float) -> dict:
    payload = dict(payload or {})
    series = dict(payload.get("series") or {})
    money_keys = {"sales", "contribution", "chain:sales", "chain:contribution"}
    for key, values in list(series.items()):
        leaf = str(key).split(":")[-1]
        if key in money_keys or leaf in {"sales", "contribution"}:
            series[key] = [_scale_int(value, factor) for value in (values or [])]
    payload["series"] = series
    return payload


def apply_supercenter_figures(state, monkeypatch=None, *, cash: int = TARGET_CASH, week: int = TARGET_WEEK, move: int = TARGET_MOVE) -> None:
    """Inject seven-figure HQ figures in the UI layer only (no engine change)."""
    source = 0
    for wid in range(0, 8):
        source = _week_revenue(state, wid)
        if source:
            break
    if not source:
        source = sum(int(item.revenue or 0) for item in (state.history or [])[:7]) or 1
    factor = week / source
    scale_state_to_supercenter(state, cash=cash, week=week)
    import open_late.ui.hq_adapter as adapter
    import open_late.ui.hq_economy as economy_ui

    orig_impact = adapter.economy_store_impact
    orig_spark = adapter.economy_sparklines

    def wrapped_impact(*args, **kwargs):
        return _scale_impact(orig_impact(*args, **kwargs), week=week, move=move)

    def wrapped_spark(*args, **kwargs):
        return _scale_spark_payload(orig_spark(*args, **kwargs), factor)

    if monkeypatch is not None:
        monkeypatch.setattr(adapter, "economy_store_impact", wrapped_impact)
        monkeypatch.setattr(economy_ui, "economy_store_impact", wrapped_impact)
        monkeypatch.setattr(adapter, "economy_sparklines", wrapped_spark)
        monkeypatch.setattr(economy_ui, "economy_sparklines", wrapped_spark)
    else:
        adapter.economy_store_impact = wrapped_impact
        economy_ui.economy_store_impact = wrapped_impact
        adapter.economy_sparklines = wrapped_spark
        economy_ui.economy_sparklines = wrapped_spark


def _text(widget) -> str:
    parts = []
    if isinstance(widget, QLabel):
        parts.append(widget.text())
    for child in widget.findChildren(QLabel):
        parts.append(child.text())
    return "\n".join(parts)


def _label_fits(lab: QLabel) -> bool:
    if lab is None or not lab.text() or lab.width() <= 1:
        return True
    if not lab.isVisible():
        return True
    fm = lab.fontMetrics()
    text = lab.text()
    if lab.wordWrap():
        bounds = fm.boundingRect(QRect(0, 0, lab.width(), 4000), Qt.TextFlag.TextWordWrap, text)
        return bounds.height() <= lab.height() + 6
    return fm.horizontalAdvance(text) <= lab.width() + 2


def test_money_compact_formats_millions_to_two_decimals_and_keeps_exact_on_money():
    assert money(1_840_000) == "$1,840,000"
    assert money(12_600_000) == "$12,600,000"
    assert money_compact(1_840_000) == "$1.84M"
    assert money_compact(1_200_000) == "$1.2M"
    assert money_compact(12_600_000) == "$12.6M"
    assert money_compact(2_000_000) == "$2M"
    assert money_compact(-1_200_000) == "-$1.2M"
    assert money_compact_signed(1_840_000) == "+$1.84M"
    assert money_compact_signed(-1_200_000) == "−$1.2M"
    # Exact form is unchanged and is what tooltips / ledgers should show.
    assert money(1_840_000) == "$1,840,000"
    assert money_compact(128_400) == "$128.4k"
    assert money_compact(850) == "$850"


def test_supercenter_figures_fit_on_dashboard_table_and_economy(tmp_path, monkeypatch):
    app, window = _boot(tmp_path, monkeypatch)
    _advance(window.state, 12)
    apply_supercenter_figures(window.state, monkeypatch)
    window.refresh()
    app.processEvents()

    cash_txt = money_compact(TARGET_CASH)
    week_txt = money_compact(TARGET_WEEK)
    move_txt = money_compact_signed(TARGET_MOVE)
    assert cash_txt == "$12.6M"
    assert week_txt == "$1.84M"
    assert move_txt == "−$1.2M"

    for size in ((1366, 768), (1100, 700)):
        window.resize(*size)
        window._open_app("home")
        app.processEvents()
        home = window.desktop.home
        text = _text(home)
        assert cash_txt in text
        # Weekly take / trend uses compact millions, not a raw $1,840,000.
        assert "$1,840,000" not in text
        assert "$12,600,000" not in text
        drawer = home.findChild(QLabel, "kpiValue")
        tray = window.desktop.topbar.cash
        assert cash_txt in (tray.text() if tray is not None else "")
        assert money(TARGET_CASH) in (tray.toolTip() or "")
        # KPI, store table, and tray figures must not clip at either size.
        card = home.findChild(QWidget, "perfCard")
        assert card is not None
        assert "SHARE OF CHAIN" in _text(card)
        kpi_names = ("kpiDrawer", "kpiTake", "kpiContribution")
        widgets = [home.findChild(QWidget, name) for name in kpi_names]
        widgets += [card, tray, home.findChild(QWidget, "revenueCard")]
        for widget in widgets:
            if widget is None:
                continue
            assert widget.width() <= window.width()
            for lab in widget.findChildren(QLabel):
                if "$" not in (lab.text() or "") and lab.objectName() not in {"kpiValue", "shareLabel", "marginLabel", "trayCash"}:
                    continue
                assert _label_fits(lab), f"{lab.objectName() or lab.text()!r} clipped at {size}: {lab.text()!r} w={lab.width()}"
        chart = home.findChild(LineChart)
        assert chart is not None
        values = [row["value"] for row in chart._rows()]
        assert any(abs(value) >= 1_000_000 for value in values)

        # Economy waterfall: chips, bar labels, and trend use compact millions.
        window._open_app("economy")
        app.processEvents()
        page = window.desktop.economy
        if page._tab != "impact":
            page._set_tab("impact")
            app.processEvents()
        eco_text = _text(page)
        assert week_txt in eco_text or money_compact(TARGET_WEEK + TARGET_MOVE) in eco_text
        assert move_txt in eco_text
        assert "$1,840,000" not in eco_text and "$1,200,000" not in eco_text
        for lab in page.findChildren(QLabel):
            if "$" not in (lab.text() or ""):
                continue
            assert _label_fits(lab), f"economy {lab.objectName() or lab.text()!r} clipped at {size}: {lab.text()!r}"
        from open_late.ui.hq_economy import WaterfallChart
        water = page.findChild(WaterfallChart)
        assert water is not None
        displays = " ".join(str(step.get("display") or "") for step in (water.steps or []))
        assert week_txt in displays or money_compact(TARGET_WEEK + TARGET_MOVE) in displays
        assert move_txt in displays or any(token.endswith("M") for token in displays.split())
        pix = window.grab()
        assert pix.width() >= 1000 and pix.height() >= 700

    window.close()
