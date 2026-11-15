"""The desk: morning notes, the day's decisions, the evening tape."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from PySide6.QtCharts import QBarCategoryAxis, QBarSeries, QBarSet, QChart, QChartView, QValueAxis
from PySide6.QtCore import QEvent, QMargins, QObject, QPointF, QRect, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from open_late.books import (
    balance_lines,
    describe_runway,
    fixtures_net,
    format_margin,
    hours_open,
    income_lines,
    oldest_stock,
    runway_days,
)
from open_late.content import HELP, LABEL_MIN_DAY, LABEL_MIN_REP, LABEL_SETUP_COST, ONLINE_SETUP_COST, SUPPLIERS
from open_late.corporate import (
    allocate,
    assign_door,
    assign_manager,
    coop_claimable,
    hire_manager,
    open_market,
    openable_markets,
    replenish,
    set_door_hours,
    set_planogram,
    sign_deal,
)
from open_late.finance import size_label
from open_late.engine import (
    answer,
    blocking,
    cancel_event,
    close_day,
    continue_morning,
    hire,
    launch_campaign,
    narrate,
    new_game,
    offer_raise,
    open_desk,
    open_label,
    open_online,
    open_site,
    owner_draw,
    place_order,
    release,
    repay_credit,
    schedule_event,
    set_assignment,
    set_hours,
    set_policy,
    set_price,
    set_supplier_terms,
    spendable_offers,
)

# E7c restock helpers. Import is guarded so the desk still loads if a build
# predates those names. The Inventory sheet uses order_qty_max and
# suggested_restock_quantities; fit_order_to_budget and place_capped_restock
# stay available for a cash-capped fill without changing Place order.
try:
    from open_late.engine import (
        fit_order_to_budget,
        order_qty_max,
        place_capped_restock,
        suggested_restock_quantities,
    )
except ImportError:  # pragma: no cover
    def order_qty_max() -> int:
        return 40

    def suggested_restock_quantities(state, supplier_id: str) -> dict[str, int]:
        return {}

    def fit_order_to_budget(state, items, budget: int) -> dict[str, int]:
        return {key: int(value) for key, value in (items or {}).items() if int(value or 0) > 0}

    def place_capped_restock(state, basket, cap: int, reserve: int, ignore_minimum: bool = True) -> int:
        return 0
from open_late.finance import pay_advice, weekly_obligations
from open_late.models import GameState
from open_late.store import SaveStore
from open_late.text import CATEGORY_LABELS, CATEGORY_SHORT, count_compact, is_sunday, money, money_axis_ticks, money_compact, weekday_name
from open_late.ui.hq_adapter import resolved_chain_id
from open_late.ui.hq_art import StorefrontArt
from open_late.ui.hq_pages import labor_budget_ceiling
from open_late.ui.icons import app_id_for_index, app_label, index_for_app
from open_late.ui.hq_shell import HQShell, rail_label
from open_late.ui.shell import HelpDialog, fill_help_window
from open_late.ui.theme import (
    ACCENT,
    DOWN,
    HQ_MUTED,
    HQ_TITLE,
    PAINT,
    STYLESHEET,
    UP,
    load_fonts,
    set_family,
    stylesheet,
    ui_font,
)

ASSETS = Path(__file__).resolve().parent.parent / "assets"

CHICAGO = ZoneInfo("America/Chicago")
CATEGORIES = list(CATEGORY_LABELS)
ASSIGNMENTS = (
    ("floor", "Floor"),
    ("fulfillment", "Packing"),
    ("modeling", "Demo desk"),
    ("private", "Private appointment"),
    ("event", "Host"),
    ("training", "Training"),
    ("off", "Off"),
)
MILESTONES = {
    "stable_month": "Month held",
    "second_location": "Second door",
    "online_counter": "Online counter",
    "private_label": "House label",
}


def _wrap_label(text: str, width: int = 46) -> str:
    words = text.split()
    lines: list[str] = []
    line = ""
    for word in words:
        trial = word if not line else f"{line} {word}"
        if line and len(trial) > width:
            lines.append(line)
            line = word
        else:
            line = trial
    if line:
        lines.append(line)
    return "\n".join(lines)


def _wrap(text: str, role: str = "body") -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setObjectName(role)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return label


def _compact_money_in_text(text: str) -> str:
    """Swap overflow-prone exact dollars in a sentence for compact form."""
    import re

    def repl(match: re.Match) -> str:
        raw = match.group(0)
        sign = -1 if raw.startswith("-") else 1
        digits = raw.replace("-", "").replace("$", "").replace(",", "")
        try:
            return money_compact(sign * int(digits))
        except ValueError:
            return raw

    return re.sub(r"-?\$\d{1,3}(?:,\d{3})+", repl, text)


def _ink_pixmap(pix: QPixmap, color: QColor) -> QPixmap:
    """Recolor a transparent mark so a cream wordmark can sit on a light bloom."""
    out = QPixmap(pix.size())
    out.fill(Qt.GlobalColor.transparent)
    painter = QPainter(out)
    painter.drawPixmap(0, 0, pix)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(out.rect(), color)
    painter.end()
    return out


class _CardSelect(QObject):
    """A click anywhere on the card selects its radio."""

    def __init__(self, radio: QRadioButton, parent: QObject) -> None:
        super().__init__(parent)
        self._radio = radio

    def eventFilter(self, watched, event) -> bool:
        if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            self._radio.setChecked(True)
        return False


def _card(urgent: bool = False) -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("cardUrgent" if urgent else "card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(16, 14, 16, 14)
    layout.setSpacing(8)
    return frame, layout


def _stat(caption: str) -> tuple[QFrame, QLabel]:
    frame = QFrame()
    frame.setObjectName("stat")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(12, 8, 12, 10)
    layout.setSpacing(2)
    cap = QLabel(caption)
    cap.setObjectName("statCaption")
    value = QLabel("—")
    value.setObjectName("statValue")
    layout.addWidget(cap)
    layout.addWidget(value)
    return frame, value


def _figure(caption: str, value: str, tip: str = "") -> QFrame:
    frame = QFrame()
    frame.setObjectName("figure")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(14, 10, 14, 12)
    layout.setSpacing(2)
    cap = QLabel(caption)
    cap.setObjectName("figureCaption")
    amount = QLabel(value)
    amount.setObjectName("figureValue")
    if tip:
        amount.setToolTip(tip)
    layout.addWidget(cap)
    layout.addWidget(amount)
    return frame


def _chips(pairs: list[tuple[str, str]]) -> QWidget:
    row_widget = QWidget()
    row = QHBoxLayout(row_widget)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(6)
    for caption, value in pairs:
        chip = QLabel(f"{caption}  {value}")
        chip.setObjectName("chip")
        row.addWidget(chip)
    row.addStretch(1)
    return row_widget


def _rate(cents: int) -> str:
    dollars, extra = divmod(cents, 100)
    if extra == 0:
        return f"${dollars}"
    return f"${dollars}.{extra:02d}"


def _advice_line(label: str, amount: int, emphasize: bool = False) -> QHBoxLayout:
    line = QHBoxLayout()
    name = _wrap(label, "cardTitle" if emphasize else "quiet")
    name.setWordWrap(False)
    shown = _wrap(money(amount), "cardTitle" if emphasize else "body")
    shown.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    line.addWidget(name)
    line.addStretch(1)
    line.addWidget(shown)
    return line


def _deposit_advice(state: GameState, person) -> QFrame:
    advice = pay_advice(state, person)
    frame, layout = _card()
    layout.addWidget(_wrap("Direct deposit advice", "cardTitle"))
    layout.addWidget(_wrap("This is not a check. The net is the deposit.", "quiet"))
    rate = _rate(advice.rate_cents)
    layout.addLayout(_advice_line(f"Regular, {advice.regular_hours} h at {rate}", advice.regular_pay))
    if advice.overtime_hours:
        layout.addLayout(_advice_line(
            f"Overtime, {advice.overtime_hours} h at {_rate(advice.overtime_rate_cents)}",
            advice.overtime_pay,
        ))
    layout.addLayout(_advice_line("Gross", advice.gross, emphasize=True))
    layout.addLayout(_advice_line("Federal income tax", advice.federal))
    layout.addLayout(_advice_line("Social Security", advice.social))
    layout.addLayout(_advice_line("Medicare", advice.medicare))
    layout.addLayout(_advice_line("State income tax", advice.state_tax))
    layout.addLayout(_advice_line("County income tax", advice.county_tax))
    layout.addLayout(_advice_line("Net deposit", advice.net, emphasize=True))
    layout.addWidget(_wrap(
        f"Year to date {money(person.ytd_gross)} gross, {money(person.ytd_net)} deposited. "
        "Sunday pays the gross, plus the employer match. Withholding comes out of the gross.",
        "quiet",
    ))
    return frame


def _statement(title: str, rows: list[tuple[str, int]], emphasize: set[str]) -> QFrame:
    frame, layout = _card()
    layout.addWidget(_wrap(title, "section"))
    for label, amount in rows:
        line = QHBoxLayout()
        name = _wrap(label, "cardTitle" if label in emphasize else "quiet")
        name.setWordWrap(False)
        shown = _wrap(money_compact(amount), "cardTitle" if label in emphasize else "body")
        shown.setObjectName("statementAmount")
        shown.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        shown.setToolTip(money(amount))
        line.addWidget(name)
        line.addStretch(1)
        line.addWidget(shown)
        layout.addLayout(line)
    return frame


class _SalesCurve(QWidget):
    """Daily revenue as a red line with a fill. Qt's area series crashes offscreen."""

    def __init__(self, points: list[tuple[str, int]]) -> None:
        super().__init__()
        self.points = points
        self.setMinimumHeight(220)
        self.setMaximumHeight(260)
        self.setStyleSheet("background: transparent;")

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width = self.width()
        height = self.height()
        values = [value for _label, value in self.points]
        peak = max(values) if values else 0
        ceiling, ticks = money_axis_ticks(peak)
        self._axis_ceiling = ceiling
        self._axis_ticks = ticks
        painter.setFont(QFont("Selawik", 9))
        tick_w = max((painter.fontMetrics().horizontalAdvance(label) for _value, label in ticks), default=24)
        left, right, top, bottom = max(52, tick_w + 10), 12, 12, 28
        plot_w = max(1, width - left - right)
        plot_h = max(1, height - top - bottom)
        painter.setPen(QPen(QColor("#D0D5DD"), 1))
        for value, label in ticks:
            y = top + plot_h - (plot_h * (value / ceiling if ceiling else 0))
            painter.setPen(QPen(QColor("#D0D5DD"), 1))
            painter.drawLine(left, int(y), width - right, int(y))
            painter.setPen(QColor("#6B7280"))
            painter.drawText(0, int(y) - 8, left - 6, 16, int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), label)
        count = len(self.points)
        if count == 0:
            painter.end()
            return
        coords: list[QPointF] = []
        for index, (_label, value) in enumerate(self.points):
            x = left + (plot_w * index / max(1, count - 1))
            y = top + plot_h - (plot_h * value / ceiling)
            coords.append(QPointF(x, y))
            painter.setPen(QColor("#6B7280"))
            painter.drawText(int(x) - 18, height - bottom + 4, 36, 20, int(Qt.AlignmentFlag.AlignHCenter), _label)
        path = QPainterPath()
        path.moveTo(coords[0].x(), top + plot_h)
        for point in coords:
            path.lineTo(point)
        path.lineTo(coords[-1].x(), top + plot_h)
        path.closeSubpath()
        painter.fillPath(path, QColor(11, 108, 189, 70))
        painter.setPen(QPen(QColor("#0B6CBD"), 3))
        for start, end in zip(coords, coords[1:]):
            painter.drawLine(start, end)
        painter.setBrush(QColor("#3AA6A0"))
        painter.setPen(Qt.PenStyle.NoPen)
        if coords:
            last = coords[-1]
            painter.drawEllipse(last, 4, 4)
        if count < 3:
            painter.setBrush(QColor("#0B6CBD"))
            painter.setPen(Qt.PenStyle.NoPen)
            floor = top + plot_h
            for point in coords:
                painter.drawRoundedRect(int(point.x()) - 16, int(point.y()), 32, max(4, int(floor - point.y())), 6, 6)
        painter.end()


class _MoneyBars(QWidget):
    """Vertical bars with compact money ticks. Replaces QChart axes that overflow at $1M+."""

    def __init__(self, title: str, points: list[tuple[str, int]], color: str) -> None:
        super().__init__()
        self.title = title
        self.points = points
        self.bar_color = QColor(color)
        peak = max((value for _label, value in points), default=0)
        self._axis_ceiling, self._axis_ticks = money_axis_ticks(peak)
        self._bar_hits: list[tuple[QRect, str]] = []
        # Short enough that the $0 tick and day labels stay above the fold
        # when the chart sits under the P&L columns at 1100x700 and 1366x768.
        self.setFixedHeight(200)
        self.setObjectName("moneyBars")
        self.setStyleSheet("background: transparent;")
        self.setMouseTracking(True)

    def mouseMoveEvent(self, event) -> None:
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        tip = ""
        for rect, text in self._bar_hits:
            if rect.contains(pos):
                tip = text
                break
        if tip != self.toolTip():
            self.setToolTip(tip)
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        if self.toolTip():
            self.setToolTip("")
        super().leaveEvent(event)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width, height = self.width(), self.height()
        painter.setFont(QFont("Selawik", 9))
        ticks = self._axis_ticks

        ceiling = self._axis_ceiling or 10
        tick_w = max((painter.fontMetrics().horizontalAdvance(label) for _value, label in ticks), default=24)
        left = max(52, tick_w + 10)
        right, top, bottom = 12, 28, 32
        plot_w = max(1, width - left - right)
        plot_h = max(1, height - top - bottom)
        painter.setPen(QColor("#1A1A1A"))
        painter.setFont(QFont("Selawik", 13))
        painter.drawText(8, 18, self.title)
        painter.setFont(QFont("Selawik", 9))
        for value, label in ticks:
            y = top + plot_h - (plot_h * (value / ceiling if ceiling else 0))
            painter.setPen(QPen(QColor("#E4E7EC"), 1))
            painter.drawLine(left, int(y), width - right, int(y))
            painter.setPen(QColor("#5C5C5C"))
            painter.drawText(QRect(2, int(y) - 8, left - 6, 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, label)
        count = len(self.points)
        self._bar_hits = []
        if count == 0:
            painter.end()
            return
        gap = 6
        bar_w = max(8, int((plot_w - gap * max(0, count - 1)) / count))
        painter.setFont(QFont("Selawik", 9))
        for index, (label, value) in enumerate(self.points):
            x = left + index * (bar_w + gap)
            h = plot_h * (max(0, value) / ceiling if ceiling else 0)
            y = top + plot_h - h
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self.bar_color)
            painter.drawRoundedRect(int(x), int(y), bar_w, max(2, int(h)), 3, 3)
            shown = painter.fontMetrics().elidedText(label, Qt.TextElideMode.ElideRight, max(10, bar_w + gap - 2))
            tw = painter.fontMetrics().horizontalAdvance(shown)
            tx = int(x + (bar_w - tw) / 2)
            tx = max(2, min(width - tw - 2, tx))
            painter.setPen(QColor("#6B7280"))
            painter.drawText(QRect(tx, height - bottom + 2, tw, bottom - 4), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter, shown)
            tip = f"{label}  ·  {money(int(value))}"
            self._bar_hits.append((QRect(int(x), top, bar_w + gap, plot_h + bottom), tip))
        painter.end()


class _Donut(QWidget):
    """Ring chart. Weights are relative."""

    def __init__(
        self,
        slices: list[tuple[str, float, str]],
        *,
        center: str = "",
        legend: bool = True,
        hole: str = "#F4F6FA",
    ) -> None:
        super().__init__()
        self.slices = [(label, value, color) for label, value, color in slices if value > 0]
        self.center = center
        self.legend = legend
        self.hole = hole
        self.setStyleSheet("background: transparent;")
        self.setMinimumHeight(96 if not legend else 210)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width = self.width()
        height = self.height()
        legend_h = 0
        if self.legend:
            legend_h = 22 + 18 * max(1, len(self.slices))
        side = max(64, min(width - 16, height - legend_h - 8))
        left = (width - side) / 2
        top = 6
        rect = (int(left), int(top), int(side), int(side))
        total = sum(value for _label, value, _color in self.slices) or 1
        angle = 90 * 16
        if not self.slices:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#D0D5DD"))
            painter.drawEllipse(*rect)
        for label, value, color in self.slices:
            span = int(-360 * 16 * value / total)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(color))
            painter.drawPie(*rect, angle, span)
            angle += span
        hole = int(side * 0.62)
        painter.setBrush(QColor(self.hole))
        painter.drawEllipse(int(left + (side - hole) / 2), int(top + (side - hole) / 2), hole, hole)
        if self.center:
            painter.setPen(QColor("#1A1A1A"))
            font = QFont("Segoe UI")
            font.setPixelSize(max(12, int(side * 0.16)))
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(int(left), int(top), int(side), int(side), int(Qt.AlignmentFlag.AlignCenter), self.center)
        if self.legend:
            font = QFont("Segoe UI")
            font.setPixelSize(11)
            painter.setFont(font)
            y = int(top + side + 10)
            for label, value, color in self.slices:
                painter.setBrush(QColor(color))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(12, y + 3, 10, 10)
                painter.setPen(QColor("#5C5C5C"))
                share = int(round(100 * value / total))
                painter.drawText(30, y, width - 42, 16, int(Qt.AlignmentFlag.AlignVCenter), f"{label}  {share}%")
                y += 18
        painter.end()


class _Radar(QWidget):
    """Shop shape. Each axis is 0 to 100."""

    def __init__(self, axes: list[tuple[str, float]]) -> None:
        super().__init__()
        self.axes = axes or [("Shop", 0)]
        self.setMinimumHeight(250)
        self.setStyleSheet("background: transparent;")

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        count = len(self.axes)
        cx = self.width() / 2
        cy = self.height() / 2 + 4
        radius = min(self.width(), self.height()) * 0.32
        painter.setPen(QPen(QColor("#D0D5DD"), 1))
        for ring in (0.35, 0.65, 1.0):
            path = QPainterPath()
            for index in range(count):
                angle = -math.pi / 2 + index * 2 * math.pi / count
                x = cx + math.cos(angle) * radius * ring
                y = cy + math.sin(angle) * radius * ring
                if index == 0:
                    path.moveTo(x, y)
                else:
                    path.lineTo(x, y)
            path.closeSubpath()
            painter.drawPath(path)
        for index, (label, _value) in enumerate(self.axes):
            angle = -math.pi / 2 + index * 2 * math.pi / count
            painter.drawLine(QPointF(cx, cy), QPointF(cx + math.cos(angle) * radius, cy + math.sin(angle) * radius))
            painter.setPen(QColor("#6B7280"))
            font = QFont("Segoe UI")
            font.setPixelSize(10)
            painter.setFont(font)
            lx = cx + math.cos(angle) * (radius + 28)
            ly = cy + math.sin(angle) * (radius + 18)
            painter.drawText(int(lx) - 36, int(ly) - 8, 72, 16, int(Qt.AlignmentFlag.AlignCenter), label)
            painter.setPen(QPen(QColor("#D0D5DD"), 1))
        shape = QPainterPath()
        for index, (_label, value) in enumerate(self.axes):
            angle = -math.pi / 2 + index * 2 * math.pi / count
            reach = radius * max(0.0, min(100.0, value)) / 100
            x = cx + math.cos(angle) * reach
            y = cy + math.sin(angle) * reach
            if index == 0:
                shape.moveTo(x, y)
            else:
                shape.lineTo(x, y)
        shape.closeSubpath()
        painter.fillPath(shape, QColor(11, 108, 189, 80))
        painter.setPen(QPen(QColor("#3AA6A0"), 2))
        painter.drawPath(shape)
        painter.setBrush(QColor("#3AA6A0"))
        painter.setPen(Qt.PenStyle.NoPen)
        for index, (_label, value) in enumerate(self.axes):
            angle = -math.pi / 2 + index * 2 * math.pi / count
            reach = radius * max(0.0, min(100.0, value)) / 100
            painter.drawEllipse(QPointF(cx + math.cos(angle) * reach, cy + math.sin(angle) * reach), 3.5, 3.5)
        painter.end()


class _BubbleGrid(QWidget):
    """Category by price band. Cell numbers are units on the shelf."""

    def __init__(self, columns: list[str], rows: list[str], values: list[list[int]]) -> None:
        super().__init__()
        self.columns = columns
        self.rows = rows
        self.values = values
        self.setMinimumHeight(280)
        self.setStyleSheet("background: transparent;")

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        columns = self.columns or ["—"]
        rows = self.rows or ["—"]
        left, top = 64, 26
        grid_w = max(1, self.width() - left - 8)
        grid_h = max(1, self.height() - top - 8)
        cell_w = grid_w / len(columns)
        cell_h = grid_h / len(rows)
        peak = max((value for line in self.values for value in line), default=1) or 1
        header = QFont("Segoe UI")
        header.setPixelSize(10)
        painter.setFont(header)
        painter.setPen(QColor("#6B7280"))
        for index, name in enumerate(columns):
            painter.drawText(int(left + index * cell_w), 4, int(cell_w), 18, int(Qt.AlignmentFlag.AlignCenter), name)
        low = QColor("#9ED0EA")
        mid = QColor("#0B6CBD")
        high = QColor("#3AA6A0")
        for row, name in enumerate(rows):
            painter.setPen(QColor("#6B7280"))
            painter.drawText(0, int(top + row * cell_h), left - 6, int(cell_h), int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight), name)
            for col in range(len(columns)):
                value = self.values[row][col] if row < len(self.values) and col < len(self.values[row]) else 0
                cx = left + col * cell_w + cell_w / 2
                cy = top + row * cell_h + cell_h / 2
                if value <= 0:
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QColor("#D0D5DD"))
                    painter.drawEllipse(QPointF(cx, cy), 5, 5)
                    continue
                level = value / peak
                color = _blend(low, mid, min(1.0, level * 1.6)) if level < 0.55 else _blend(mid, high, (level - 0.55) / 0.45)
                radius = min(cell_w, cell_h) * (0.22 + 0.24 * level)
                painter.setBrush(color)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(QPointF(cx, cy), radius, radius)
                painter.setPen(QColor("#1A1A1A"))
                font = QFont("Segoe UI")
                font.setPixelSize(11)
                font.setBold(True)
                painter.setFont(font)
                painter.drawText(int(cx - radius), int(cy - 8), int(radius * 2), 16, int(Qt.AlignmentFlag.AlignCenter), str(value))
        painter.end()


class _Meters(QWidget):
    def __init__(self, rows: list[tuple[str, float, str]]) -> None:
        super().__init__()
        self.rows = rows
        self.setMinimumHeight(max(72, 28 * len(rows) + 8))
        self.setStyleSheet("background: transparent;")

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = QFont("Segoe UI")
        font.setPixelSize(11)
        painter.setFont(font)
        for index, (label, value, color) in enumerate(self.rows):
            y = 4 + index * 28
            painter.setPen(QColor("#5C5C5C"))
            painter.drawText(0, y, 108, 16, int(Qt.AlignmentFlag.AlignVCenter), label)
            track = (112, y + 4, max(20, self.width() - 156), 8)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#E4E7EC"))
            painter.drawRoundedRect(*track, 4, 4)
            filled = int(track[2] * max(0.0, min(100.0, value)) / 100)
            painter.setBrush(QColor(color))
            painter.drawRoundedRect(track[0], track[1], max(4, filled), track[3], 4, 4)
            painter.setPen(QColor("#1A1A1A"))
            painter.drawText(self.width() - 40, y, 40, 16, int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), str(int(value)))
        painter.end()


class _Sparkline(QWidget):
    """Small trend line under a score card."""

    def __init__(self, values: list[float], color: str = "#E4C36A") -> None:
        super().__init__()
        self.values = list(values) if values else [0.0, 0.0]
        self.color = QColor(color)
        self.setMinimumHeight(46)
        self.setStyleSheet("background: transparent;")

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        values = self.values
        if len(values) == 1:
            values = [values[0] * 0.7, values[0]]
        low = min(values)
        high = max(values)
        span = max(high - low, abs(high) * 0.2, 1)
        width = self.width()
        height = self.height()
        left, right, top, bottom = 2, 2, 6, 4
        plot_w = max(1, width - left - right)
        plot_h = max(1, height - top - bottom)
        coords: list[QPointF] = []
        for index, value in enumerate(values):
            x = left + plot_w * index / max(1, len(values) - 1)
            y = top + plot_h - plot_h * ((value - low) / span)
            coords.append(QPointF(x, y))
        fill = QPainterPath()
        fill.moveTo(coords[0].x(), top + plot_h)
        for point in coords:
            fill.lineTo(point)
        fill.lineTo(coords[-1].x(), top + plot_h)
        fill.closeSubpath()
        wash = QColor(self.color)
        wash.setAlpha(70)
        painter.fillPath(fill, wash)
        painter.setPen(QPen(self.color, 2))
        for start, end in zip(coords, coords[1:]):
            painter.drawLine(start, end)
        painter.setBrush(self.color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(coords[-1], 3.2, 3.2)
        painter.end()


class _HeatField(QWidget):
    """Glowing category field, quiet plum through hot gold."""

    def __init__(self, spots: list[tuple[str, float]]) -> None:
        super().__init__()
        self.spots = spots
        self.setMinimumHeight(210)
        self.setStyleSheet("background: transparent;")

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width = max(1, self.width())
        height = max(1, self.height())
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#F4F6FA"))
        painter.drawRoundedRect(0, 0, width, height - 22, 12, 12)
        anchors = [
            (0.22, 0.42), (0.40, 0.30), (0.58, 0.38), (0.74, 0.26),
            (0.66, 0.62), (0.36, 0.68), (0.80, 0.58),
        ]
        peak = max((value for _label, value in self.spots), default=1) or 1
        field = self.spots or [("Quiet", 0)]
        for index, (_label, value) in enumerate(field):
            ax, ay = anchors[index % len(anchors)]
            level = max(0.0, min(1.0, value / peak))
            color = _blend(QColor("#9ED0EA"), QColor("#E4C36A"), level)
            center = QPointF(width * ax, (height - 22) * ay)
            radius = 28 + 36 * level
            glow = QRadialGradient(center, radius)
            hot = QColor(color)
            hot.setAlpha(210)
            edge = QColor(color)
            edge.setAlpha(0)
            glow.setColorAt(0.0, hot)
            glow.setColorAt(1.0, edge)
            painter.setBrush(glow)
            painter.drawEllipse(center, radius, radius)
        painter.setPen(QColor("#6B7280"))
        font = QFont("Segoe UI")
        font.setPixelSize(10)
        painter.setFont(font)
        painter.drawText(8, height - 18, width // 2, 16, int(Qt.AlignmentFlag.AlignLeft), "Quiet")
        painter.setPen(QColor("#E4C36A"))
        painter.drawText(width // 2, height - 18, width // 2 - 8, 16, int(Qt.AlignmentFlag.AlignRight), "Hot")
        painter.end()


def _blend(start: QColor, end: QColor, amount: float) -> QColor:
    amount = max(0.0, min(1.0, amount))
    return QColor(
        int(start.red() + (end.red() - start.red()) * amount),
        int(start.green() + (end.green() - start.green()) * amount),
        int(start.blue() + (end.blue() - start.blue()) * amount),
    )


def _fill(scroll: QScrollArea, build, margins: tuple[int, int, int, int] = (22, 18, 22, 22), stretch: bool = True) -> None:
    inner = QWidget()
    layout = QVBoxLayout(inner)
    layout.setContentsMargins(*margins)
    layout.setSpacing(12)
    build(layout)
    if stretch:
        layout.addStretch(1)
    scroll.setWidget(inner)


def _logo(supplier_id: str, height: int = 64) -> QLabel:
    label = QLabel()
    label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    label.setStyleSheet("background: transparent; border: none;")
    path = ASSETS / "brands" / f"{supplier_id}.png"
    if path.exists():
        pixmap = QPixmap(str(path)).scaledToHeight(
            height,
            Qt.TransformationMode.SmoothTransformation,
        )
        label.setPixmap(pixmap)
        label.setFixedHeight(height + 8)
    return label


def _photo(product_id: str, size: int = 72) -> QLabel:
    label = QLabel()
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setStyleSheet("background: transparent; border: none;")
    path = ASSETS / "products" / f"{product_id}.png"
    if path.exists():
        pixmap = QPixmap(str(path)).scaled(
            size,
            size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        label.setPixmap(pixmap)
    return label


def _limits(person) -> str:
    lines = []
    if "no_modeling" in person.boundaries or person.comfort_modeling < 35:
        lines.append("no product photography")
    if "no_private" in person.boundaries:
        lines.append("no private appointments")
    if "no_events" in person.boundaries:
        lines.append("no hosting")
    if "no_intense_demo" in person.boundaries:
        lines.append("no pharmacy-counter demos")
    if not lines:
        return "No hard limit on the card."
    return "Limits: " + ", ".join(lines) + "."


def _when(stamp: str) -> str:
    try:
        parsed = datetime.fromisoformat(stamp)
    except ValueError:
        return stamp
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(CHICAGO).strftime("%b %d, %I:%M %p CT")


class MainWindow(QMainWindow):
    def __init__(self, store: SaveStore | None = None):
        super().__init__()
        family = load_fonts()
        set_family(family)
        self.store = store or SaveStore()
        self.state: GameState | None = None
        self._supplier_id = "noir"
        self._desk_index = 0
        self._order_spins: dict[str, QSpinBox] = {}
        self._order_qtys: dict[str, int] = {}
        self._inv_query = ""
        self._inv_dept = ""
        self._inv_page = 0
        self.desktop: HQShell | None = None
        self.shell: HQShell | None = None
        self._pending_app = None
        self._chosen_chain_id = None
        self._chosen_economy = "standard"
        self._picker_cards = {}
        self.setWindowTitle("Retail Rivals")
        logo = ASSETS / "brand" / "retail_rivals_logo.png"
        mark = logo if logo.exists() else ASSETS / "brand" / "mark.png"
        if not mark.exists():
            mark = ASSETS / "brand" / "mark.jpg"
        if mark.exists():
            self.setWindowIcon(QIcon(str(mark)))
        self.setMinimumSize(1100, 720)
        self.resize(1366, 768)
        self.setStyleSheet(stylesheet(family))
        self._build()
        self.refresh()

    def _build(self) -> None:
        shell = QWidget()
        shell.setObjectName("shell")
        outer = QVBoxLayout(shell)
        outer.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget()
        self.stack.setObjectName("pages")
        outer.addWidget(self.stack)
        self.setCentralWidget(shell)
        self._build_menu()
        self._build_title()
        self._build_setup()
        self._build_picker()
        self._build_play()

    def _build_menu(self) -> None:
        # Actions live in the Start menu. Keep the bar hidden so the desk reads as a desktop.
        self.menuBar().hide()
        file_menu = self.menuBar().addMenu("File")
        file_menu.addAction("New shop", self._show_setup)
        file_menu.addAction("Save now", self._save)
        file_menu.addAction("Front door", self._front)
        help_menu = self.menuBar().addMenu("Help")
        help_menu.addAction("How the desk works", self._help)

    def _build_title(self) -> None:
        from open_late.ui.desktop import GlassPanel, Stage

        page = Stage()
        page.setObjectName("nightPage")
        overlay = QWidget(page)
        overlay.setObjectName("titleOverlay")
        overlay.setStyleSheet("QWidget#titleOverlay { background: transparent; }")
        outer = QHBoxLayout(overlay)
        outer.setContentsMargins(48, 36, 48, 36)
        outer.setSpacing(36)
        left = QVBoxLayout()
        left.setSpacing(14)
        left.addStretch(2)
        left.addWidget(_wrap("AFTER HOURS", "kicker"))
        wordmark = QLabel()
        wordmark.setObjectName("logo")
        logo_path = ASSETS / "brand" / "retail_rivals_logo.png"
        if logo_path.exists():
            pix = QPixmap(str(logo_path)).scaled(
                520, 200,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            wordmark.setPixmap(pix)
        else:
            wordmark.setText("Retail Rivals")
        left.addWidget(wordmark)
        left.addWidget(_wrap("Seven chains. One office. The week is yours to run.", "deck"))
        left.addStretch(3)
        outer.addLayout(left, stretch=5)

        door = GlassPanel(page, radius=14)
        door.setObjectName("door")
        door.setMinimumWidth(360)
        door.setMaximumWidth(460)
        column = QVBoxLayout(door)
        column.setContentsMargins(22, 22, 22, 22)
        column.setSpacing(12)
        column.addWidget(_wrap("On the books", "section"))
        self.save_box = QVBoxLayout()
        self.save_box.setSpacing(8)
        column.addLayout(self.save_box)
        new_button = QPushButton("Open a new shop")
        new_button.setObjectName("newShop")
        new_button.clicked.connect(self._show_setup)
        column.addWidget(new_button, alignment=Qt.AlignmentFlag.AlignLeft)
        how = QPushButton("How the desk works")
        how.setObjectName("quiet")
        how.clicked.connect(self._help)
        column.addWidget(how, alignment=Qt.AlignmentFlag.AlignLeft)
        right = QVBoxLayout()
        right.addStretch(1)
        right.addWidget(door)
        right.addStretch(1)
        outer.addLayout(right, stretch=4)
        self.title_page = page
        self._title_overlay = overlay
        page.resizeEvent = self._fit_title_overlay
        self.stack.addWidget(page)

    def _fit_title_overlay(self, event) -> None:
        page = self.title_page
        Stage = type(page)
        Stage.resizeEvent(page, event)
        if hasattr(self, "_title_overlay"):
            self._title_overlay.setGeometry(page.rect())

    def _build_setup(self) -> None:
        from open_late.ui.desktop import GlassPanel, Stage

        page = Stage()
        page.setObjectName("nightPage")
        overlay = QWidget(page)
        overlay.setObjectName("setupOverlay")
        overlay.setStyleSheet("QWidget#setupOverlay { background: transparent; }")
        outer = QHBoxLayout(overlay)
        outer.setContentsMargins(36, 28, 36, 28)
        outer.addStretch(1)
        door = GlassPanel(page, radius=14)
        door.setObjectName("door")
        door.setMinimumWidth(520)
        door.setMaximumWidth(680)
        column = QVBoxLayout(door)
        column.setContentsMargins(26, 24, 26, 24)
        column.setSpacing(12)
        setup_mark = QLabel()
        setup_mark.setObjectName("logo")
        setup_logo = ASSETS / "brand" / "retail_rivals_logo.png"
        if setup_logo.exists():
            setup_mark.setPixmap(QPixmap(str(setup_logo)).scaled(
                280, 110,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))
        else:
            setup_mark.setText("Retail Rivals")
        column.addWidget(setup_mark, alignment=Qt.AlignmentFlag.AlignLeft)
        column.addWidget(_wrap("Name the shop", "section"))
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Retail Rivals")
        self.name_input.setText("Retail Rivals")
        self.name_input.textChanged.connect(self._sync_start)
        column.addWidget(self.name_input)
        self.shop_radio = QRadioButton("Neighborhood store")
        self.online_radio = QRadioButton("Online counter only")
        self.corporate_radio = QRadioButton("Corporate office")
        self.shop_radio.setChecked(True)
        group = QButtonGroup(self)
        group.addButton(self.shop_radio)
        group.addButton(self.online_radio)
        group.addButton(self.corporate_radio)
        column.addWidget(self._choice_card(
            self.shop_radio,
            "Rent is $1,200 on Sunday. A loud sign gets the block talking. Alyssa and Jordan start on the floor.",
        ))
        column.addWidget(self._choice_card(
            self.online_radio,
            "No rent. Chris packs, Marisol writes the careful emails. Events wait until you rent a room.",
        ))
        column.addWidget(self._choice_card(
            self.corporate_radio,
            "You are the office. Dana Ruiz runs Evansville. You set the wall, the ads, the truck, and the deals. Seattle, Houston, Las Vegas, and Naperville are the other leases.",
        ))
        self.age_check = QCheckBox("Everyone in this shop is an adult. This is a retail management game.")
        self.age_check.toggled.connect(self._sync_start)
        column.addWidget(self.age_check)
        row = QHBoxLayout()
        back = QPushButton("Back")
        back.setObjectName("quiet")
        back.clicked.connect(self._front)
        self.start_button = QPushButton("Choose a chain")
        self.start_button.setObjectName("startGame")
        self.start_button.clicked.connect(self._show_picker)
        row.addWidget(back)
        row.addWidget(self.start_button)
        row.addStretch(1)
        column.addLayout(row)
        right = QVBoxLayout()
        right.addStretch(1)
        right.addWidget(door)
        right.addStretch(1)
        outer.addLayout(right)
        outer.addStretch(1)
        self.setup_page = page
        self._setup_overlay = overlay
        page.resizeEvent = self._fit_setup_overlay
        self.stack.addWidget(page)
        self._sync_start()

    def _fit_setup_overlay(self, event) -> None:
        page = self.setup_page
        Stage = type(page)
        Stage.resizeEvent(page, event)
        if hasattr(self, "_setup_overlay"):
            self._setup_overlay.setGeometry(page.rect())

    def _build_picker(self) -> None:
        from open_late.ui.desktop import GlassPanel, Stage
        from open_late.ui.hq_adapter import chain_catalog, chain_logo_path, default_chain_id

        page = Stage()
        page.setObjectName("nightPage")
        overlay = QWidget(page)
        overlay.setObjectName("pickerOverlay")
        overlay.setStyleSheet("QWidget#pickerOverlay { background: transparent; }")
        outer = QVBoxLayout(overlay)
        outer.setContentsMargins(36, 24, 36, 24)
        outer.setSpacing(12)
        mark = QLabel()
        logo = ASSETS / "brand" / "retail_rivals_logo.png"
        if logo.exists():
            mark.setPixmap(QPixmap(str(logo)).scaled(
                280, 96,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))
        else:
            mark.setText("Retail Rivals")
        outer.addWidget(mark, alignment=Qt.AlignmentFlag.AlignLeft)
        outer.addWidget(_wrap("Pick the chain", "section"))
        outer.addWidget(_wrap("Retail Rivals stays the game. The chain you pick is the fascia on every door.", "deck"))
        door = GlassPanel(page, radius=14)
        door.setObjectName("door")
        column = QVBoxLayout(door)
        column.setContentsMargins(18, 18, 18, 18)
        grid = QGridLayout()
        grid.setSpacing(12)
        self._picker_cards = {}
        self._chosen_chain_id = default_chain_id()
        for index, row in enumerate(chain_catalog()):
            ident = str(row.get("id") or "")
            card = QFrame()
            card.setObjectName("storeCard")
            card.setCursor(Qt.CursorShape.PointingHandCursor)
            box = QVBoxLayout(card)
            box.setContentsMargins(10, 10, 10, 10)
            box.setSpacing(8)
            logo_lab = QLabel()
            logo_lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
            logo_lab.setMinimumHeight(86)
            path = chain_logo_path(row)
            pix = QPixmap(str(path)) if path.exists() else QPixmap()
            if not pix.isNull():
                logo_lab.setPixmap(pix.scaled(
                    180, 86,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                ))
            else:
                logo_lab.setText(str(row.get("name") or ident))
            name = QLabel(str(row.get("name") or ident))
            name.setAlignment(Qt.AlignmentFlag.AlignCenter)
            name.setObjectName("pickerChainName")
            box.addWidget(logo_lab)
            box.addWidget(name)
            card.mousePressEvent = lambda event, i=ident: self._pick_chain(i)  # noqa: E731
            self._picker_cards[ident] = card
            grid.addWidget(card, index // 4, index % 4)
        column.addLayout(grid)
        self._chosen_economy = "standard"
        eco = QHBoxLayout()
        eco.setSpacing(12)
        eco.addWidget(_wrap("Economy", "section"))
        self.economy_group = QButtonGroup(self)
        self.economy_radios = {}
        for key, label in (("calm", "Calm"), ("standard", "Standard"), ("stern", "Stern")):
            radio = QRadioButton(label)
            radio.setObjectName("economyPick")
            radio.setChecked(key == "standard")
            radio.toggled.connect(lambda on, k=key: self._set_economy(k) if on else None)
            self.economy_group.addButton(radio)
            self.economy_radios[key] = radio
            eco.addWidget(radio)
        eco_help = _wrap("Standard is the usual week. Calm is gentler. Stern swings harder.", "quiet")
        eco_help.setWordWrap(False)
        eco.addSpacing(16)
        eco.addWidget(eco_help)
        eco.addStretch(1)
        column.addLayout(eco)
        row = QHBoxLayout()
        back = QPushButton("Back")
        back.setObjectName("quiet")
        back.clicked.connect(self._show_setup)
        self.picker_start = QPushButton("Start the game")
        self.picker_start.setObjectName("startGame")
        self.picker_start.clicked.connect(self._start)
        row.addWidget(back)
        row.addWidget(self.picker_start)
        row.addStretch(1)
        column.addLayout(row)
        outer.addWidget(door, stretch=1)
        self.picker_page = page
        self._picker_overlay = overlay
        page.resizeEvent = self._fit_picker_overlay
        self.stack.addWidget(page)
        self._paint_picker()

    def _fit_picker_overlay(self, event) -> None:
        page = self.picker_page
        Stage = type(page)
        Stage.resizeEvent(page, event)
        if hasattr(self, "_picker_overlay"):
            self._picker_overlay.setGeometry(page.rect())

    def _show_picker(self) -> None:
        if not self.age_check.isChecked() or not self.name_input.text().strip():
            return
        self.stack.setCurrentWidget(self.picker_page)
        self._paint_picker()

    def _pick_chain(self, chain_id: str) -> None:
        self._chosen_chain_id = chain_id
        self._paint_picker()

    def _set_economy(self, difficulty: str) -> None:
        self._chosen_economy = difficulty or "standard"

    def _paint_picker(self) -> None:
        chosen = self._chosen_chain_id or "megamart"
        for ident, card in self._picker_cards.items():
            on = ident == chosen
            card.setObjectName("storeCardOn" if on else "storeCard")
            if on:
                card.setStyleSheet(
                    "QFrame#storeCardOn { background: #FFFFFF; border: 2px solid #0070F0; border-radius: 12px; }"
                    "QLabel { background: transparent; border: none; color: #122033; }"
                )
            else:
                card.setStyleSheet(
                    "QFrame#storeCard { background: #FFFFFF; border: 1px solid #E3E7EE; border-radius: 12px; }"
                    "QLabel { background: transparent; border: none; color: #122033; }"
                )
            card.style().unpolish(card)
            card.style().polish(card)

    def _choice_card(self, radio: QRadioButton, body: str) -> QFrame:
        frame, layout = _card()
        layout.addWidget(radio)
        note = _wrap(body, "quiet")
        note.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        note.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout.addWidget(note)
        frame.setCursor(Qt.CursorShape.PointingHandCursor)
        picker = _CardSelect(radio, frame)
        frame.installEventFilter(picker)
        return frame

    def _build_play(self) -> None:
        self.shell = HQShell()
        self.desktop = self.shell
        self.play_page = self.shell
        self.shell.set_host(self)
        self.shell.open_app.connect(self._open_app)
        self.shell.open_floor.connect(self._to_desk)
        self.shell.close_day.connect(self._close)
        self.shell.next_morning.connect(self._next)
        self.shell.new_shop.connect(self._show_setup)
        self.shell.save_now.connect(self._save)
        self.shell.front_door.connect(self._front)
        self.shell.help.connect(self._help)
        self.shell.scope_changed.connect(self._on_scope_changed)
        self.to_desk = self.shell.to_desk
        self.close_button = self.shell.close_button
        self.next_button = self.shell.next_button
        self.status = self.shell.status
        # Kept so older helpers that mention a sidebar note do not break.
        self.sidebar_note = self.status
        self.header_actions = QHBoxLayout()
        self.stack.addWidget(self.shell)

    def _scroll_page(self) -> tuple[QWidget, QScrollArea]:
        page = QWidget()
        column = QVBoxLayout(page)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        column.addWidget(scroll, stretch=1)
        return page, scroll

    def _phase_page(self, button_text: str, slot) -> tuple[QWidget, QScrollArea, QPushButton]:
        page = QWidget()
        column = QVBoxLayout(page)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        column.addWidget(scroll, stretch=1)
        bar = QFrame()
        bar.setObjectName("bar")
        row = QHBoxLayout(bar)
        row.setContentsMargins(22, 12, 22, 12)
        button = QPushButton(button_text)
        button.clicked.connect(slot)
        row.addStretch(1)
        row.addWidget(button)
        column.addWidget(bar)
        return page, scroll, button

    def _build_header(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("header")
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(22, 14, 18, 14)
        layout.setSpacing(12)
        self.header_name = QLabel("Retail Rivals")
        self.header_name.setObjectName("shopName")
        self.header_meta = QLabel()
        self.header_meta.setObjectName("dayChip")
        help_button = QPushButton("?")
        help_button.setObjectName("quiet")
        help_button.setFixedWidth(36)
        help_button.clicked.connect(self._help)
        self.header_owner = QLabel("Owner")
        self.header_owner.setObjectName("userChip")
        layout.addWidget(self.header_name)
        layout.addStretch(1)
        layout.addWidget(self.header_meta)
        layout.addWidget(help_button)
        layout.addWidget(self.header_owner)
        self.header_actions = QHBoxLayout()
        self.header_actions.setSpacing(8)
        layout.addLayout(self.header_actions)
        return frame

    def refresh(self) -> None:
        if self.state is None:
            self.stack.setCurrentWidget(self.title_page)
            self._render_title()
            return
        assert self.desktop is not None
        self.stack.setCurrentWidget(self.play_page)
        self.desktop.set_corporate(self.state.mode == "corporate")
        self.desktop.set_chain_chrome(self.state)
        self._render_header()
        self._render_widgets()
        self._render_notifications()
        if self.state.phase == "morning":
            self._show_phase_window("home")
            self._maybe_toast()
        else:
            current_id = getattr(self.desktop, "current_id", None)
            first_class = {"home", "stores", "pos", "planograms", "economy", "help", "expansion"}
            if current_id in first_class:
                current = current_id
            else:
                current = app_id_for_index(self._desk_index)
                if current == "overview":
                    current = "home"
                elif current == "expansion" and self.state.mode == "corporate":
                    current = "stores"
            self._show_phase_window(current)
        self.desktop.layout_chrome()
        self.desktop.lift_chrome()

    def _render_title(self) -> None:
        while self.save_box.count():
            item = self.save_box.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        saves = self.store.list_saves()
        if not saves:
            self.save_box.addWidget(_wrap("No shops on the books yet.", "quiet"))
            return
        for slot, name, day, cash, updated in saves:
            frame, layout = _card()
            layout.addWidget(_wrap(name, "cardTitle"))
            layout.addWidget(_wrap(f"Day {day} · {money(cash)} · saved {_when(updated)}", "quiet"))
            row = QHBoxLayout()
            resume = QPushButton("Continue")
            resume.clicked.connect(lambda _=False, key=slot: self._load(key))
            delete = QPushButton("Delete")
            delete.setObjectName("quiet")
            delete.clicked.connect(lambda _=False, key=slot, shop=name: self._delete(key, shop))
            row.addWidget(resume)
            row.addWidget(delete)
            row.addStretch(1)
            layout.addLayout(row)
            self.save_box.addWidget(frame)

    def _render_header(self) -> None:
        state = self.state
        assert state is not None and self.desktop is not None
        urgent = len(blocking(state)) if state.phase in ("morning", "desk") else 0
        pending = sum(1 for message in self.state.inbox if not message.resolved)
        if state.phase == "morning":
            clock = f"{state.open_hour:02d}:00"
            day = f"{weekday_name(state.day)[:3]}  ·  Day {state.day}  ·  Morning"
        elif state.phase == "desk":
            clock = f"{state.open_hour:02d}:00"
            day = f"Floor open {state.open_hour:02d}:00–{state.close_hour:02d}:00  ·  Day {state.day}"
        else:
            clock = f"{state.close_hour:02d}:00"
            day = f"{weekday_name(state.day)[:3]}  ·  Day {state.day}  ·  {state.phase.title()}"
        badge = urgent or pending if state.phase == "morning" else urgent
        self.desktop.topbar.set_tray(money_compact(state.cash), badge, day, cash_tip=money(state.cash))
        self.desktop.topbar.set_phase(state.phase, failed=state.failed, urgent=badge)
        self.desktop.topbar.set_scope_menu(state)
        self.desktop.topbar.set_scope_label(*self.desktop.scope, state)
        self.desktop.rail.set_inbox(pending, urgent)
        meta = f"{weekday_name(state.day)}  ·  Day {state.day}  ·  {state.phase.title()}"
        self.desktop.center.set_header(clock, meta, money_compact(state.cash), urgent, f"{state.review_score:.1f}", cash_tip=money(state.cash))

    def _recommended(self) -> list[tuple[str, str, str]]:
        state = self.state
        if state is None:
            return []
        rows: list[tuple[str, str, str]] = []
        report = state.last_report
        if report.day:
            rows.append(("Yesterday's tape", f"{money_compact(report.revenue)}  ·  {count_compact(report.visits)} through the door", "sales"))
        urgent = next((m for m in state.inbox if not m.resolved and m.urgent), None)
        if urgent:
            rows.append((urgent.title, "Urgent  ·  needs an answer before you close", "journal"))
        offer = next((m for m in state.inbox if not m.resolved and "Supplier offer" in m.title), None)
        if offer:
            rows.append((offer.title, offer.body.split(".")[0] + ".", "orders"))
        if not rows:
            rows.append(("The floor board", "Open Overview to see the shop", "overview"))
        return rows[:3]

    def _render_morning(self) -> None:
        self._show_phase_window("overview")

    def _render_desk(self) -> None:
        self._show_phase_window(app_id_for_index(self._desk_index))

    def _tab(self, build) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        _fill(scroll, build)
        return scroll

    def _yesterday_card(self) -> QFrame:
        state = self.state
        assert state is not None
        frame, layout = _card()
        report = state.last_report
        if report.day == 0:
            layout.addWidget(_wrap("The tape is blank until you close a day. Stock is on the shelf. Sunday is when the bills hit."))
            return frame
        tape = _wrap(
            f"{report.weekday} · {money_compact(report.revenue)} · {report.units} sales · "
            f"{count_compact(report.visits)} through the door · {report.online_orders} shipped · "
            f"{report.returns} returns"
        )
        tape.setToolTip(
            f"{report.weekday} · {money(report.revenue)} · {report.units} sales · "
            f"{int(report.visits):,} through the door · {report.online_orders} shipped · "
            f"{report.returns} returns"
        )
        layout.addWidget(tape)
        if report.top_sellers:
            layout.addWidget(_wrap("Top: " + ", ".join(report.top_sellers), "quiet"))
        if report.flags:
            layout.addWidget(_wrap(report.flags[0], "quiet"))
        return frame

    def _message_card(self, message) -> QFrame:
        frame, layout = _card(urgent=message.urgent)
        title = message.title + ("  ·  urgent" if message.urgent else "")
        layout.addWidget(_wrap(title, "urgent" if message.urgent else "cardTitle"))
        layout.addWidget(_wrap(message.body))
        if message.choices:
            row = QVBoxLayout()
            row.setSpacing(6)
            for choice in message.choices:
                button = QPushButton(_wrap_label(choice.label))
                button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                if choice is not message.choices[0]:
                    button.setObjectName("quiet")
                button.clicked.connect(lambda _=False, mid=message.id, cid=choice.id: self._choose(mid, cid))
                row.addWidget(button)
            layout.addLayout(row)
        return frame

    def _resolved_card(self, message) -> QFrame:
        frame, layout = _card()
        layout.addWidget(_wrap(message.title, "quiet"))
        if message.resolution:
            layout.addWidget(_wrap(message.resolution, "quiet"))
        return frame

    def _render_sidebar(self) -> None:
        if self.desktop is None or self.state is None:
            return
        self.desktop.rail.set_active(app_id_for_index(self._desk_index) if self._desk_index is not None else 'home')

    def _goto(self, index: int) -> None:
        self._desk_index = index
        if self.state is None:
            return
        if self.state.phase == "morning":
            self._to_desk()
            return
        self._open_app(app_id_for_index(index))

    def _open_app(self, app_id: str) -> None:
        if self.state is None or self.desktop is None:
            return
        if self.state.mode != "corporate" and app_id in ("expansion", "planograms"):
            mapped = "planograms"
        else:
            mapped = {"overview": "home", "expansion": "stores"}.get(app_id, app_id)
        browse = {"home", "stores", "journal", "help", "planograms", "pos", "economy", "expansion"}
        if self.state.phase == "morning" and mapped not in browse:
            if mapped not in ("pos",):
                self._desk_index = index_for_app(app_id)
            self._pending_app = mapped
            self._to_desk()
            return
        if mapped == "planograms":
            self._desk_index = 8
        elif mapped not in ("home", "stores", "pos", "help", "economy"):
            self._desk_index = index_for_app(app_id)
        self._show_phase_window(mapped)
        self.desktop.hide_overlays()
        self.desktop.lift_chrome()

    def _body_for(self, app_id: str):
        bodies = {
            "overview": self._overview_body,
            "sales": self._sales_body,
            "inventory": self._inventory_body,
            "orders": self._orders_body,
            "staff": self._staff_body,
            "customers": self._customers_body,
            "marketing": self._marketing_body,
            "books": self._books_body,
            "expansion": self._expansion_body,
            "planograms": self._expansion_body,
            "market": self._market_body,
            "journal": self._journal_body,
            "settings": self._operations_body,
        }
        return bodies.get(app_id, self._overview_body)

    def _show_phase_window(self, app_id: str) -> None:
        assert self.desktop is not None and self.state is not None
        if self.state.mode != "corporate" and app_id in ("expansion", "planograms"):
            mapped = "planograms"
        else:
            mapped = {"overview": "home", "expansion": "stores"}.get(app_id, app_id)
        pending_app = getattr(self, "_pending_app", None)
        if pending_app:
            mapped = pending_app
            self._pending_app = None
        if mapped in ("home", "stores", "pos", "help", "planograms", "economy"):
            self.desktop.show_page(mapped)
            if mapped == "planograms" and self.state.mode != "corporate":
                self._fill_legacy("expansion")
            return
        self.desktop.show_page(mapped)
        self._fill_legacy(mapped)


    def _fill_legacy(self, app_id: str) -> None:
        layout = self.desktop.clear_module()
        kind, _scope_id = self.desktop.scope
        if kind != "all" and app_id in ("inventory", "orders"):
            layout.addWidget(_wrap(
                "Buying stays in the Evansville warehouse. The store switcher does not change a purchase order.",
                "hint",
            ))
        elif kind != "all":
            layout.addWidget(_wrap(f"Scoped to {self.desktop.scope_text()}.", "hint"))
        self._body_for(app_id)(layout)
        layout.addStretch(1)

    def _on_scope_changed(self) -> None:
        if self.state is None or self.desktop is None:
            return
        self._show_phase_window(self.desktop.current_id)

    def _fill_window(self, win, app_id: str) -> None:
        # Kept for title/setup help windows that still use mica chrome.
        if hasattr(win, "clear_body"):
            win.clear_body()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(16, 10, 22, 10)
        self._body_for(app_id)(layout)
        layout.addStretch(1)
        scroll.setWidget(inner)
        if hasattr(win, "body_layout"):
            win.body_layout.addWidget(scroll)

    def _maybe_toast(self) -> None:
        assert self.desktop is not None and self.state is not None
        urgent = next((m for m in self.state.inbox if not m.resolved and m.urgent), None)
        if urgent is None:
            return
        self._say(urgent.title)

    def _render_notifications(self) -> None:
        assert self.desktop is not None and self.state is not None
        notes = []
        pending = [m for m in self.state.inbox if not m.resolved]
        pending.sort(key=lambda m: (not m.urgent, -m.day))
        for message in pending[:5]:
            actions = []
            if message.urgent or message.choices:
                actions.append(("Review", lambda _=False, i="journal": self._open_app(i)))
            notes.append((bool(message.urgent), message.title, message.body, actions))
        self.desktop.center.set_notes(notes)

    def _on_hand(self, product_id: str) -> int:
        state = self.state
        assert state is not None
        total = 0
        line = state.stock.get(product_id)
        if line is not None:
            total += line.on_hand
        for door in state.doors:
            door_line = door.stock.get(product_id)
            if door_line is not None:
                total += door_line.on_hand
        return total

    def _mix_slices(self) -> list[tuple[str, float, str]]:
        state = self.state
        assert state is not None
        colors = ["#3AA6A0", "#C9843A", "#5B7FCF", "#C45B6A", "#6A9A4E", "#7A5CAF", "#5B6E8A"]
        totals: dict[str, int] = {}
        report = state.last_report
        if report.day and report.by_category:
            for key, amount in report.by_category.items():
                if amount:
                    totals[key] = totals.get(key, 0) + amount
        if not totals:
            for product in state.products.values():
                held = self._on_hand(product.id)
                if held:
                    totals[product.category] = totals.get(product.category, 0) + held * product.price
        if not totals:
            return [
                ("Respectable", state.reputation_respectable, "#3AA6A0"),
                ("Nightlife", state.reputation_nightlife, "#C9843A"),
            ]
        ranked = sorted(totals.items(), key=lambda item: item[1], reverse=True)
        return [
            (CATEGORY_SHORT.get(key, key), value, colors[index % len(colors)])
            for index, (key, value) in enumerate(ranked)
        ]

    def _health_axes(self) -> list[tuple[str, float]]:
        state = self.state
        assert state is not None
        employed = [person for person in state.staff if person.employed]
        working = [person for person in employed if person.assignment != "off"]
        coverage = 100 * len(working) / len(employed) if employed else 0
        units = sum(self._on_hand(product.id) for product in state.products.values())
        sunday = max(1, weekly_obligations(state))
        drawer = min(100, 100 * state.cash / (sunday * 3))
        return [
            ("Proper", state.reputation_respectable),
            ("Night", state.reputation_nightlife),
            ("Reviews", state.review_score / 5 * 100),
            ("Floor", coverage),
            ("Shelf", min(100, units / 1.5)),
            ("Drawer", drawer),
        ]

    def _shelf_grid(self) -> tuple[list[str], list[str], list[list[int]]]:
        state = self.state
        assert state is not None
        bands = [("Under 40", 0, 40), ("40–60", 40, 60), ("60–90", 60, 90), ("90+", 90, 10_000)]
        columns = [CATEGORY_SHORT[key] for key in CATEGORIES]
        grid = [[0 for _column in columns] for _band in bands]
        index = {key: position for position, key in enumerate(CATEGORIES)}
        for product in state.products.values():
            column = index.get(product.category)
            if column is None:
                continue
            held = self._on_hand(product.id)
            if held <= 0:
                continue
            for row, (_label, low, high) in enumerate(bands):
                if low <= product.price < high:
                    grid[row][column] += held
                    break
        return columns, [label for label, _low, _high in bands], grid

    def _kpi_card(self, caption: str, value: str, detail: str, percent: float, color: str) -> QFrame:
        # Used by older callers; same compact tile as the score card, no overlapping ring.
        return self._score_card(caption, value, detail, "quiet", [], color)

    def _series(self, pick) -> list[float]:
        state = self.state
        assert state is not None
        values = [float(pick(report)) for report in state.history[-12:]]
        return values or [0.0]

    def _delta_line(self, current: float, previous: float | None) -> tuple[str, str]:
        if previous is None or previous == 0:
            return "First close on the tape", "quiet"
        change = 100 * (current - previous) / abs(previous)
        arrow = "↑" if change >= 0 else "↓"
        return f"{arrow}  {abs(change):.1f}% vs the day before", "up" if change >= 0 else "down"

    def _score_card(self, caption: str, value: str, detail: str, role: str, series: list[float], color: str, tip: str = "") -> QFrame:
        frame, layout = _card()
        frame.setObjectName("kpi")
        layout.setSpacing(2)
        layout.setContentsMargins(12, 10, 12, 10)
        cap = _wrap(caption, "figureCaption")
        cap.setWordWrap(False)
        val = _wrap(value, "heroValue")
        val.setObjectName("figureValue")
        val.setWordWrap(False)
        val.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        if tip:
            val.setToolTip(tip)
        note = _wrap(detail, role)
        note.setWordWrap(True)
        note.setMinimumHeight(32)
        layout.addWidget(cap)
        layout.addWidget(val)
        layout.addWidget(note)
        if series:
            spark_color = UP if role == "up" else (DOWN if role == "down" else color)
            spark = _Sparkline(series, spark_color)
            spark.setFixedHeight(36)
            spark.setMaximumHeight(36)
            layout.addWidget(spark)
        frame.setMinimumHeight(118)
        frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        return frame

    def _widget_board(self, layout: QVBoxLayout) -> None:
        state = self.state
        assert state is not None
        report = state.last_report
        previous = state.history[-2] if len(state.history) >= 2 else None
        revenue = float(report.revenue if report.day else 0)
        visits = float(report.visits if report.day else 0)
        conversion = (100 * report.units / report.visits) if report.day and report.visits else 0.0
        cash = float(report.cash_end or state.cash)
        prev_revenue = float(previous.revenue) if previous else None
        prev_visits = float(previous.visits) if previous else None
        prev_conversion = (100 * previous.units / previous.visits) if previous and previous.visits else None
        prev_cash = float(previous.cash_end) if previous else None

        def line(current: float, prior: float | None) -> tuple[str, str]:
            return self._delta_line(current, prior if report.day else None)

        revenue_detail, revenue_role = line(revenue, prev_revenue)
        visits_detail, visits_role = line(visits, prev_visits)
        conversion_detail, conversion_role = line(conversion, prev_conversion)
        cash_detail, cash_role = line(cash, prev_cash)
        grid = QGridLayout()
        grid.setSpacing(10)
        tiles = [
            ("DAY'S TAKE", money_compact(int(revenue)), revenue_detail, revenue_role, self._series(lambda item: item.revenue), money(int(revenue))),
            ("THROUGH THE DOOR", count_compact(int(visits)) if report.day else "—", visits_detail, visits_role, self._series(lambda item: item.visits), f"{int(visits):,}" if report.day else ""),
            ("CONVERSION", f"{conversion:.1f}%" if report.day else "—", conversion_detail, conversion_role, self._series(lambda item: (100 * item.units / item.visits) if item.visits else 0), ""),
            ("DRAWER", money_compact(int(cash)), cash_detail, cash_role, self._series(lambda item: item.cash_end or 0), money(int(cash))),
        ]
        for index, (caption, value, detail, role, series, tip) in enumerate(tiles):
            color = UP if role == "up" else (DOWN if role == "down" else ACCENT)
            grid.addWidget(self._score_card(caption, value, detail, role, series, color, tip=tip), index // 2, index % 2)
        layout.addLayout(grid)

        lead = self._mix_slices()
        if lead and report.day:
            insight = f"{lead[0][0]} is carrying the tape. The drivers beside it are what the floor is actually doing."
        elif lead:
            insight = f"The shelf is weighted toward {lead[0][0]}. Close a day and the take line starts."
        else:
            insight = "The board is waiting on a closed day."
        bar, bar_layout = _card()
        bar.setObjectName("hero")
        row = QHBoxLayout()
        text = QVBoxLayout()
        text.addWidget(_wrap("KEY NOTE", "figureCaption"))
        text.addWidget(_wrap(insight))
        row.addLayout(text, stretch=1)
        open_sales = QPushButton("Open sales")
        open_sales.setObjectName("quiet")
        open_sales.clicked.connect(lambda _=False: self._goto(1))
        row.addWidget(open_sales, alignment=Qt.AlignmentFlag.AlignVCenter)
        bar_layout.addLayout(row)
        layout.addWidget(bar)

        # One chart row, not three, so the board still fits inside a window at 1100.
        charts = QHBoxLayout()
        charts.setSpacing(12)
        trend_card, trend_layout = _card()
        trend_layout.addWidget(_wrap("Take over time", "cardTitle"))
        if state.history:
            color = DOWN if revenue_role == "down" else (UP if revenue_role == "up" else ACCENT)
            curve = _Sparkline(self._series(lambda item: item.revenue), color)
            curve.setMinimumHeight(100)
            trend_layout.addWidget(curve)
        else:
            trend_layout.addWidget(_wrap("The line starts when a day closes.", "quiet"))
        charts.addWidget(trend_card, stretch=1)
        heat_card, heat_layout = _card()
        heat_layout.addWidget(_wrap("Category heat", "cardTitle"))
        heat = _HeatField([(label, value) for label, value, _color in self._mix_slices()])
        heat.setMinimumHeight(100)
        heat_layout.addWidget(heat)
        charts.addWidget(heat_card, stretch=1)
        layout.addLayout(charts)

    def _render_widgets(self) -> None:
        if self.desktop is None or self.state is None:
            return
        if self.desktop.current_id == "home":
            self.desktop.home.rebuild()
        elif self.desktop.current_id == "stores":
            self.desktop.stores.rebuild()
        elif self.desktop.current_id == "pos":
            self.desktop.pos_page.rebuild()
        elif self.desktop.current_id == "planograms":
            self.desktop.planogram.rebuild()
        elif self.desktop.current_id == "economy":
            self.desktop.economy.rebuild()

    def _fill_today_widget(self) -> None:
        assert self.desktop is not None and self.state is not None
        if getattr(self.desktop, "today", None) is None:
            return
        box = self.desktop.today.box
        while box.count() > 1:
            item = box.takeAt(1)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
            elif item.layout() is not None:
                layout = item.layout()
                while layout.count():
                    child = layout.takeAt(0)
                    w = child.widget()
                    if w is not None:
                        w.hide()
                        w.setParent(None)
                        w.deleteLater()
        state = self.state
        report = state.last_report
        previous = state.history[-2] if len(state.history) >= 2 else None
        revenue = float(report.revenue if report.day else 0)
        visits = float(report.visits if report.day else 0)
        conversion = (100 * report.units / report.visits) if report.day and report.visits else 0.0
        cash = float(state.cash)
        def detail(current, prior):
            text, role = self._delta_line(current, prior if report.day else None)
            return text, role
        metrics = [
            ("DAY'S TAKE", money_compact(int(revenue)), money(int(revenue)), *detail(revenue, float(previous.revenue) if previous else None)),
            ("THROUGH THE DOOR", count_compact(int(visits)) if report.day else "—", f"{int(visits):,}" if report.day else "", *detail(visits, float(previous.visits) if previous else None)),
            ("CONVERSION", f"{conversion:.1f}%" if report.day else "—", "", *detail(conversion, (100 * previous.units / previous.visits) if previous and previous.visits else None)),
            ("DRAWER", money_compact(int(cash)), money(int(cash)), *detail(cash, float(previous.cash_end) if previous and previous.cash_end else None)),
        ]
        # One metric per row so captions and deltas never clip at 1100.
        repeated = all(role == "quiet" and text.startswith("First close") for _c, _v, text, role in metrics)
        for caption, value, tip, text, role in metrics:
            row = QHBoxLayout()
            row.setContentsMargins(0, 2, 0, 0)
            row.setSpacing(8)
            cap = _wrap(caption, "figureCaption")
            cap.setWordWrap(False)
            val = _wrap(value, "cardTitle")
            val.setObjectName("todayValue")
            val.setWordWrap(False)
            val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if tip:
                val.setToolTip(tip)
            row.addWidget(cap, stretch=1)
            row.addWidget(val)
            box.addLayout(row)
            if not repeated and text:
                note = _wrap(text, role)
                note.setWordWrap(True)
                box.addWidget(note)
        if repeated:
            box.addWidget(_wrap("First close on the tape", "quiet"))
        self.desktop.today.setMinimumHeight(200)
        self.desktop.today.adjustSize()

    def _fill_staff_widget(self) -> None:
        assert self.desktop is not None and self.state is not None
        box = self.desktop.people.box
        while box.count() > 1:
            item = box.takeAt(1)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        people = [person for person in self.state.staff if person.employed and person.assignment != "off"]
        if not people:
            box.addWidget(_wrap("Nobody is assigned this morning.", "quiet"))
        roles = {key: label for key, label in ASSIGNMENTS}
        for person in people:
            row = QHBoxLayout()
            row.setContentsMargins(0, 4, 0, 4)
            parts = person.name.split()
            initials = (parts[0][:1] + (parts[-1][:1] if len(parts) > 1 else "")).upper()
            avatar = QLabel(initials)
            avatar.setObjectName("avatar")
            avatar.setFixedSize(32, 32)
            avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
            text = QVBoxLayout()
            text.setSpacing(0)
            text.addWidget(_wrap(person.name, "cardTitle"))
            text.addWidget(_wrap(roles.get(person.assignment, person.assignment), "quiet"))
            row.addWidget(avatar)
            row.addLayout(text, stretch=1)
            row.addWidget(_wrap(f"Mood {person.mood}", "quiet"))
            wrap = QWidget()
            wrap.setObjectName("staffRow")
            wrap.setStyleSheet("QWidget#staffRow { background: transparent; }")
            wrap.setLayout(row)
            box.addWidget(wrap)
        self.desktop.people.setMinimumHeight(140)
        self.desktop.people.adjustSize()

    def _overview_body(self, layout: QVBoxLayout) -> None:
        state = self.state
        assert state is not None
        report = state.last_report
        previous = state.history[-2] if len(state.history) >= 2 else None
        title_row = QHBoxLayout()
        title_col = QVBoxLayout()
        title_col.addWidget(_wrap("FLOOR BOARD", "kicker"))
        when = f"{report.weekday} · day {report.day}" if report.day else "No day has closed yet"
        title_col.addWidget(_wrap(when, "quiet"))
        title_row.addLayout(title_col)
        title_row.addStretch(1)
        layout.addLayout(title_row)
        if state.phase == "gameover" and state.fail_reason:
            layout.addWidget(_wrap(state.fail_reason, "urgent"))
        self._widget_board(layout)
        if state.doors:
            strip = QHBoxLayout()
            strip.setSpacing(10)
            for door in state.doors:
                manager = next((person.name for person in state.managers if person.id == door.manager_id), "No manager")
                frame, inner = _card()
                inner.addWidget(_wrap(f"{door.city}, {door.state_name}", "cardTitle"))
                if door.status == "buildout":
                    inner.addWidget(_wrap(f"{manager} · build-out, opens day {door.opens_on}", "quiet"))
                else:
                    door_line = _wrap(
                        f"{manager} · {money_compact(door.last_sales)} yesterday · {money_compact(door.last_contribution)} last week",
                        "quiet",
                    )
                    door_line.setToolTip(
                        f"{manager} · {money(door.last_sales)} yesterday · {money(door.last_contribution)} last week"
                    )
                    inner.addWidget(door_line)
                inner.addWidget(_wrap(f"Wall match {door.compliance} · tax {door.sales_tax_bps / 100:.2f}%".replace(".00%", "%"), "hint"))
                strip.addWidget(frame, stretch=1)
            layout.addLayout(strip)

        board = QHBoxLayout()
        board.setSpacing(12)
        hero, hero_layout = _card()
        hero.setObjectName("hero")
        hero_layout.addWidget(_wrap("TOTAL REVENUE", "figureCaption"))
        hero_amt = _wrap(money_compact(report.revenue) if report.day else money(0), "heroValue")
        hero_amt.setObjectName("figureValue")
        if report.day:
            hero_amt.setToolTip(money(report.revenue))
        hero_layout.addWidget(hero_amt)
        if previous and previous.revenue:
            delta = int(round(100 * (report.revenue - previous.revenue) / previous.revenue))
            hero_layout.addWidget(_wrap(f"{delta:+}% vs the day before", "up" if delta >= 0 else "down"))
        elif report.day:
            hero_layout.addWidget(_wrap("First close on the tape.", "quiet"))
        else:
            hero_layout.addWidget(_wrap("The tape starts when you close the day.", "quiet"))
        stats = QHBoxLayout()
        transactions = report.units if report.day else 0
        average = report.revenue // transactions if transactions else 0
        for caption, value in (
            ("TRANSACTIONS", str(transactions)),
            ("AVERAGE SALE", money(average) if transactions else money(0)),
            ("UNITS SOLD", str(report.units if report.day else 0)),
        ):
            stats.addWidget(_figure(caption, value), stretch=1)
        hero_layout.addLayout(stats)
        chart = self._revenue_chart()
        if chart is not None:
            hero_layout.addWidget(chart)
        board.addWidget(hero, stretch=3)
        board.addWidget(self._top_products_card(), stretch=2)
        layout.addLayout(board)

        lower = QHBoxLayout()
        lower.setSpacing(12)
        lower.setAlignment(Qt.AlignmentFlag.AlignTop)
        shift = self._shift_card()
        shift.setMinimumWidth(340)
        alerts = self._alerts_card()
        lower.addWidget(shift, stretch=5)
        lower.addWidget(alerts, stretch=6)
        layout.addLayout(lower)
        drawer = QHBoxLayout()
        drawer.setSpacing(10)
        for caption, value, tip in (
            ("DRAWER", money_compact(state.cash), money(state.cash)),
            ("TAX HELD", money_compact(state.tax_held), money(state.tax_held)),
            ("SUNDAY", money_compact(weekly_obligations(state)), money(weekly_obligations(state))),
            ("REVIEWS", f"{state.review_score:.1f}", ""),
        ):
            drawer.addWidget(_figure(caption, value, tip), stretch=1)
        layout.addLayout(drawer)
        if state.phase in ("evening", "gameover"):
            frame, inner = _card()
            inner.addWidget(_wrap("The tape", "cardTitle"))
            inner.addWidget(_wrap(narrate(state, report)))
            layout.addWidget(frame)

    def _top_products_card(self) -> QFrame:
        state = self.state
        assert state is not None
        frame, layout = _card()
        header = QHBoxLayout()
        header.addWidget(_wrap("TOP PRODUCTS", "cardTitle"))
        header.addStretch(1)
        layout.addLayout(header)
        report = state.last_report
        ranked = sorted(report.units_by_product.items(), key=lambda item: item[1], reverse=True)
        ranked = [(product_id, qty) for product_id, qty in ranked if qty and product_id in state.products][:5]
        if not ranked:
            if state.mode == "corporate" and state.doors:
                def on_floor(product_id: str) -> int:
                    return sum(door.stock[product_id].on_hand for door in state.doors if product_id in door.stock)
                shelf = sorted(state.products.values(), key=lambda product: on_floor(product.id) * product.price, reverse=True)
                ranked = [(product.id, on_floor(product.id)) for product in shelf if on_floor(product.id)][:5]
                layout.addWidget(_wrap("Nothing has sold yet. This is what is on the floors.", "quiet"))
            else:
                shelf = sorted(state.products.values(), key=lambda product: state.stock[product.id].on_hand * product.price, reverse=True)
                ranked = [(product.id, state.stock[product.id].on_hand) for product in shelf if state.stock[product.id].on_hand][:5]
                layout.addWidget(_wrap("Nothing has sold yet. This is what is on the shelf.", "quiet"))
        if not ranked:
            layout.addWidget(_wrap("The shelf is empty.", "quiet"))
            return frame
        for rank, (product_id, qty) in enumerate(ranked, start=1):
            product = state.products[product_id]
            row = QHBoxLayout()
            row.setSpacing(8)
            row.addWidget(_wrap(str(rank), "quiet"))
            row.addWidget(_photo(product.id, 40))
            name = QVBoxLayout()
            name.addWidget(_wrap(product.name))
            name.addWidget(_wrap(f"{product.brand} · {qty} on the tape" if report.units_by_product.get(product_id) else f"{product.brand} · {qty} on hand", "quiet"))
            row.addLayout(name, stretch=1)
            shown = product.price * qty if report.units_by_product.get(product_id) else product.price
            amount = _wrap(money_compact(shown))
            amount.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            amount.setToolTip(money(shown))
            row.addWidget(amount)
            holder = QWidget()
            holder.setLayout(row)
            holder.setMaximumHeight(56)
            layout.addWidget(holder)
        layout.addStretch(1)
        return frame

    def _shift_card(self) -> QFrame:
        state = self.state
        assert state is not None
        frame, layout = _card()
        roles = {
            "floor": "Sales",
            "fulfillment": "Stock",
            "modeling": "Demo desk",
            "private": "Private appointment",
            "event": "Event",
            "training": "Training",
            "off": "Off",
        }
        on_shift = [person for person in state.staff if person.employed and person.assignment != "off"]
        scheduled = [person for person in state.staff if person.employed]
        header = QHBoxLayout()
        header.addWidget(_wrap("STAFF ON SHIFT", "cardTitle"))
        header.addStretch(1)
        header.addWidget(_wrap(f"{len(on_shift)} / {len(scheduled)}", "quiet"))
        layout.addLayout(header)
        if not on_shift:
            if state.mode == "corporate":
                layout.addWidget(_wrap("No shift is posted. The manager writes it when the day closes.", "quiet"))
            else:
                layout.addWidget(_wrap("Nobody is assigned. The floor is thin until you set the sheet.", "quiet"))
            return frame
        for person in on_shift:
            row = QHBoxLayout()
            parts = person.name.split()
            letters = (parts[0][:1] + (parts[-1][:1] if len(parts) > 1 else "")).upper()
            avatar = QLabel(letters)
            avatar.setObjectName("avatar")
            avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
            row.addWidget(avatar)
            text = QVBoxLayout()
            text.setSpacing(0)
            text.addWidget(_wrap(person.name))
            text.addWidget(_wrap(roles.get(person.assignment, person.assignment), "quiet"))
            row.addLayout(text, stretch=1)
            pay = _wrap(f"{money(person.wage)} gross", "quiet")
            pay.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            row.addWidget(pay)
            layout.addLayout(row)
        layout.addStretch(1)
        return frame

    def _alerts_card(self) -> QFrame:
        state = self.state
        assert state is not None
        frame, layout = _card()
        pending = [message for message in state.inbox if not message.resolved]
        pending.sort(key=lambda message: (not message.urgent, -message.day))
        header = QHBoxLayout()
        header.addWidget(_wrap("ALERTS", "cardTitle"))
        header.addStretch(1)
        header.addWidget(_wrap(str(len(pending)) if pending else "Clear", "quiet"))
        layout.addLayout(header)
        if is_sunday(state.day):
            layout.addWidget(_wrap(f"Sunday. Closing takes about {money(weekly_obligations(state))}.", "urgent"))
        if state.phase == "desk" and blocking(state):
            layout.addWidget(_wrap("Urgent notes are still open. The day will not close until you answer them.", "urgent"))
        if not pending:
            layout.addWidget(_wrap("Nothing is waiting.", "quiet"))
            return frame
        for message in pending[:6]:
            layout.addWidget(self._message_card(message))
        layout.addStretch(1)
        return frame

    def _sales_body(self, layout: QVBoxLayout) -> None:
        state = self.state
        assert state is not None
        layout.addWidget(_wrap("Sales", "section"))
        report = state.last_report
        if report.day == 0:
            layout.addWidget(_wrap("No close yet. The overview fills in after the first day.", "quiet"))
            return
        story = narrate(state, report)
        shown = _compact_money_in_text(story)
        shown = shown.replace(f"{int(report.visits)} people came through", f"{count_compact(report.visits)} people came through")
        tape = _wrap(shown)
        tape.setObjectName("salesNarrate")
        tape.setToolTip(story)
        layout.addWidget(tape)
        chart = self._category_chart()
        if chart is not None:
            layout.addWidget(chart)

    def _orders_body(self, layout: QVBoxLayout) -> None:
        state = self.state
        assert state is not None
        layout.addWidget(_wrap("Orders", "section"))
        layout.addWidget(_wrap("Open purchase orders. New ones are written from Inventory.", "quiet"))
        if not state.orders:
            layout.addWidget(_wrap("Nothing is on the way.", "quiet"))
            return
        for order in state.orders:
            supplier = SUPPLIERS.get(order.supplier_id)
            name = supplier.name if supplier else order.supplier_id
            lines = ", ".join(
                f"{state.products[product_id].name} × {qty}"
                for product_id, qty in order.lines.items()
                if product_id in state.products
            )
            frame, inner = _card()
            inner.addWidget(_wrap(name, "cardTitle"))
            inner.addWidget(_wrap(
                f"Arrives day {order.arrives_on}. Goods {money(order.cost)}. Freight {money(order.freight)}.",
            ))
            inner.addWidget(_wrap(lines, "quiet"))
            layout.addWidget(frame)

    def _inbox_body(self, layout: QVBoxLayout) -> None:
        state = self.state
        assert state is not None
        pending = [message for message in state.inbox if not message.resolved]
        if not pending:
            layout.addWidget(_wrap("Nothing unresolved.", "quiet"))
        for message in reversed(pending):
            layout.addWidget(self._message_card(message))

    def _inventory_body(self, layout: QVBoxLayout) -> None:
        state = self.state
        assert state is not None
        if state.mode == "corporate":
            layout.addWidget(_wrap(
                "Orders land in the Evansville warehouse. A store does not call the factory. "
                "Send the truck from Stores. Apparel is still a size run, XS through XL.",
                "quiet",
            ))
        else:
            layout.addWidget(_wrap(
                "Grocery and general merchandise share this sheet. Apparel lands as a size run, XS through XL. "
                "Cash orders leave the drawer now, freight included. Net 14 waits until the relationship is there.",
                "quiet",
            ))
        combo = QComboBox()
        combo.setObjectName("supplierCombo")
        for supplier in SUPPLIERS.values():
            if supplier.id == "labelco" and not state.flags.private_label:
                continue
            combo.addItem(supplier.name, supplier.id)
        index = max(0, combo.findData(self._supplier_id))
        combo.setCurrentIndex(index)
        self._supplier_id = combo.currentData() or "noir"
        combo.currentIndexChanged.connect(self._supplier_changed)
        layout.addWidget(combo)
        self._supplier_combo = combo
        actions = QHBoxLayout()
        suggest = QPushButton("Fill a modest restock")
        suggest.setObjectName("quiet")
        suggest.clicked.connect(self._suggest)
        actions.addWidget(suggest)
        place = QPushButton("Place order")
        place.setMinimumHeight(32)
        place.clicked.connect(self._place)
        actions.addWidget(place)
        actions.addStretch(1)
        layout.addLayout(actions)
        supplier = SUPPLIERS[self._supplier_id]
        account = next((item for item in state.supplier_accounts if item.supplier_id == supplier.id), None)
        relationship = account.relationship if account else 0
        terms = {"net14": "net 14", "net30": "net 30"}.get(account.terms, "cash") if account else "cash"
        if state.mode == "corporate":
            deal = next((item for item in state.deals if item.supplier_id == supplier.id), None)
            if deal is not None:
                terms += (
                    f", {deal.cost_off_percent}% under the sheet, "
                    f"co-op accrued {money(deal.coop_accrued)}"
                )
        payable = money(account.payable) if account else money(0)
        lines = ", ".join(supplier.brands)
        layout.addWidget(_logo(supplier.id))
        layout.addWidget(_wrap(
            f"{supplier.blurb} Lines: {lines}. {supplier.price_tier} tier. "
            f"Lead time {supplier.lead_time_days} days. Minimum {money(supplier.minimum_order)}. "
            f"Relationship {relationship}. Terms {terms}. Open bill {payable}.",
            "quiet",
        ))
        terms_row = QHBoxLayout()
        cash_terms = QPushButton("Cash with the order")
        cash_terms.setObjectName("quiet")
        cash_terms.clicked.connect(lambda _=False, sid=supplier.id: self._terms(sid, "cash"))
        net_terms = QPushButton("Ask for net 14")
        net_terms.setObjectName("quiet")
        net_terms.clicked.connect(lambda _=False, sid=supplier.id: self._terms(sid, "net14"))
        terms_row.addWidget(cash_terms)
        terms_row.addWidget(net_terms)
        terms_row.addStretch(1)
        layout.addLayout(terms_row)
        policy = QHBoxLayout()
        stance = _wrap("Buying stance", "quiet")
        stance.setWordWrap(False)
        policy.addWidget(stance)
        for key, label in (
            ("keep_light", "Keep it light"),
            ("balanced", "Balanced"),
            ("lean_in", "Lean in"),
        ):
            button = QPushButton(label)
            if state.flags.policy != key:
                button.setObjectName("quiet")
            button.clicked.connect(lambda _=False, choice=key: self._policy(choice))
            policy.addWidget(button)
        policy.addStretch(1)
        layout.addLayout(policy)
        filters = QHBoxLayout()
        filters.setSpacing(8)
        search = QLineEdit()
        search.setObjectName("inventorySearch")
        search.setPlaceholderText("Search name, id, brand, or department…")
        search.setText(self._inv_query)
        search.textChanged.connect(self._inv_search_changed)
        filters.addWidget(search, stretch=1)
        dept = QComboBox()
        dept.setObjectName("inventoryDept")
        dept.addItem("All departments", "")
        seen = []
        for product in state.products.values():
            if product.supplier_id != self._supplier_id:
                continue
            key = self._product_dept(product)
            if key and key not in seen:
                seen.append(key)
        for key in seen:
            dept.addItem(CATEGORY_LABELS.get(key, key.replace("_", " ").title()), key)
        index = max(0, dept.findData(self._inv_dept))
        dept.setCurrentIndex(index)
        dept.currentIndexChanged.connect(self._inv_dept_changed)
        filters.addWidget(dept)
        layout.addLayout(filters)
        products = self._inventory_products(state)
        head = QWidget()
        head.setObjectName("invHead")
        head.setStyleSheet("QWidget#invHead { background: transparent; }")
        labels = QHBoxLayout(head)
        labels.setContentsMargins(8, 2, 8, 6)
        labels.setSpacing(10)
        cols = (("Item", 0, 1), ("On hand", 130, 0), ("Age", 40, 0), ("Price", 84, 0), ("Order", 72, 0))
        for heading, width, stretch in cols:
            lab = _wrap(heading.upper(), "figureCaption")
            lab.setWordWrap(False)
            if width:
                lab.setFixedWidth(width)
                if heading == "Age":
                    lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
            labels.addWidget(lab, stretch=stretch)
        layout.addWidget(head)
        page_size = 18
        total = len(products)
        pages = max(1, (total + page_size - 1) // page_size) if total else 1
        if self._inv_page >= pages:
            self._inv_page = pages - 1
        if self._inv_page < 0:
            self._inv_page = 0
        start = self._inv_page * page_size
        page_rows = products[start:start + page_size]
        list_host = QWidget()
        list_host.setObjectName("inventoryList")
        list_box = QVBoxLayout(list_host)
        list_box.setContentsMargins(0, 0, 0, 0)
        list_box.setSpacing(0)
        self._order_spins = {}
        last_dept = None
        for product in page_rows:
            ident_key = self._product_dept(product)
            if ident_key != last_dept:
                header = _wrap(CATEGORY_LABELS.get(ident_key, ident_key.replace("_", " ").title() or "Other"), "section")
                header.setObjectName(f"inventoryDeptHeader_{ident_key}")
                list_box.addWidget(header)
                last_dept = ident_key
            line = state.stock[product.id]
            row = QFrame()
            row.setObjectName("inventoryRow")
            row.setProperty("productId", product.id)
            row.setStyleSheet("background: transparent; border-bottom: 1px solid rgba(0,0,0,22);")
            box = QHBoxLayout(row)
            box.setContentsMargins(8, 6, 8, 6)
            box.setSpacing(10)
            box.addWidget(_photo(product.id, 48))
            ident = QVBoxLayout()
            ident.setSpacing(0)
            name = _wrap(product.name, "cardTitle")
            name.setWordWrap(False)
            meta = _wrap(f"{product.brand}  ·  {product.quality}/5  ·  {product.trend}", "quiet")
            meta.setWordWrap(False)
            ident.addWidget(name)
            ident.addWidget(meta)
            box.addLayout(ident, stretch=1)
            on_hand = size_label(line) if line.sizes else str(line.on_hand)
            held = _wrap(on_hand)
            held.setWordWrap(True)
            held.setFixedWidth(130)
            box.addWidget(held)
            age = _wrap(str(line.age_days) if line.on_hand else "—", "quiet")
            age.setAlignment(Qt.AlignmentFlag.AlignCenter)
            age.setFixedWidth(40)
            box.addWidget(age)
            price = QSpinBox()
            price.setRange(product.cost, product.cost * 5)
            price.setPrefix("$")
            price.setFixedWidth(84)
            price.setValue(product.price)
            price.valueChanged.connect(lambda value, pid=product.id: self._priced(pid, value))
            box.addWidget(price)
            qty = QSpinBox()
            qty.setObjectName(f"inventoryQty_{product.id}")
            qty.setRange(0, order_qty_max())
            qty.setFixedWidth(72)
            qty.setValue(int(self._order_qtys.get(product.id, 0)))
            qty.valueChanged.connect(lambda value, pid=product.id: self._inv_qty_changed(pid, value))
            self._order_spins[product.id] = qty
            box.addWidget(qty)
            row.setMinimumHeight(64)
            list_box.addWidget(row)
        if not page_rows:
            list_box.addWidget(_wrap("No SKUs match this search.", "quiet"))
        list_box.addStretch(1)
        scroller = QScrollArea()
        scroller.setObjectName("inventoryScroll")
        scroller.setWidgetResizable(True)
        scroller.setFrameShape(QFrame.Shape.NoFrame)
        list_host.setMinimumHeight(0)
        list_host.adjustSize()
        list_host.setMinimumHeight(list_host.sizeHint().height())
        scroller.setMinimumHeight(280)
        scroller.setWidget(list_host)
        layout.addWidget(scroller, stretch=1)
        pager = QHBoxLayout()
        prev = QPushButton("Prev")
        prev.setObjectName("inventoryPrev")
        prev.setEnabled(start > 0)
        prev.clicked.connect(lambda: self._inv_step_page(-1))
        nxt = QPushButton("Next")
        nxt.setObjectName("inventoryNext")
        nxt.setEnabled(start + len(page_rows) < total)
        nxt.clicked.connect(lambda: self._inv_step_page(1))
        page_lab = _wrap(
            f"{start + 1}–{start + len(page_rows)} of {total}" if total else "0 SKUs",
            "quiet",
        )
        page_lab.setObjectName("inventoryPage")
        pager.addWidget(prev)
        pager.addWidget(page_lab)
        pager.addWidget(nxt)
        pager.addStretch(1)
        layout.addLayout(pager)

    def _staff_body(self, layout: QVBoxLayout) -> None:
        state = self.state
        assert state is not None
        if state.mode == "corporate":
            layout.addWidget(_wrap(
                "You hire the managers and place the floor. A manager writes the shifts for their city. "
                "A raise and a severance still come from the office.",
                "quiet",
            ))
            layout.addWidget(_wrap("Managers", "section"))
            for person in state.managers:
                layout.addWidget(self._manager_card(person))
        else:
            layout.addWidget(_wrap("One assignment each. A limit on the card is still a limit if you schedule past it.", "quiet"))
        employed = [person for person in state.staff if person.employed]
        waiting = [person for person in state.staff if not person.employed]
        layout.addWidget(_wrap("On the sheet", "section"))
        if not employed:
            layout.addWidget(_wrap("Nobody is scheduled. The shop cannot open like this.", "urgent"))
        for person in employed:
            layout.addWidget(self._staff_card(person, employed=True))
        if waiting:
            layout.addWidget(_wrap("Available", "section"))
            for person in waiting:
                layout.addWidget(self._staff_card(person, employed=False))

    def _staff_card(self, person, employed: bool) -> QFrame:
        frame, layout = _card()
        layout.addWidget(_wrap(person.name, "cardTitle"))
        layout.addWidget(_wrap(person.short))
        layout.addWidget(_chips([
            ("Knowledge", str(person.product_knowledge)),
            ("Demos", str(person.comfort_modeling)),
            ("Reliability", str(person.reliability)),
            ("Gross", f"{money(person.wage)}/wk"),
            ("Sales", money(person.sales_attributed)),
        ]))
        layout.addWidget(_wrap(_limits(person), "hint"))
        if employed:
            layout.addWidget(_chips([
                ("Mood", str(person.mood)),
                ("Burnout", str(person.burnout)),
                ("Loyalty", str(person.loyalty)),
                ("Following", str(person.following)),
                (person.personality.capitalize(), "on the floor" if person.assignment == "floor" else person.assignment),
            ]))
            row = QHBoxLayout()
            hint = _wrap("", "urgent")
            managed = False
            if self.state is not None and self.state.mode == "corporate":
                door = next((item for item in self.state.doors if item.id == person.door_id), None)
                manager = next((item for item in self.state.managers if door and item.id == door.manager_id), None)
                managed = manager is not None
                if managed and door is not None:
                    layout.addWidget(_wrap(f"{manager.name} writes the schedule at {door.city}.", "quiet"))
                places = QComboBox()
                places.addItem("No door", "")
                for item in self.state.doors:
                    places.addItem(item.city, item.id)
                places.setCurrentIndex(max(0, places.findData(person.door_id)))
                places.currentIndexChanged.connect(
                    lambda _index, sid=person.id, box=places: self._place_staff(sid, box)
                )
                row.addWidget(places, stretch=1)
            if not managed:
                combo = QComboBox()
                for key, label in ASSIGNMENTS:
                    combo.addItem(label, key)
                combo.setCurrentIndex(max(0, combo.findData(person.assignment)))
                combo.currentIndexChanged.connect(
                    lambda _index, sid=person.id, box=combo, note=hint: self._assign(sid, box, note)
                )
                row.addWidget(combo, stretch=1)
            raise_pay = QPushButton("Raise")
            raise_pay.setObjectName("quiet")
            raise_pay.clicked.connect(lambda _=False, sid=person.id: self._raise(sid))
            row.addWidget(raise_pay)
            let_go = QPushButton("Let go")
            let_go.setObjectName("quiet")
            let_go.clicked.connect(lambda _=False, sid=person.id, who=person.name, wage=person.wage: self._release(sid, who, wage))
            row.addWidget(let_go)
            layout.addLayout(row)
            layout.addWidget(hint)
            assert self.state is not None
            layout.addWidget(_deposit_advice(self.state, person))
        else:
            hire_button = QPushButton(f"Hire · {money(person.wage)} / week")
            hire_button.clicked.connect(lambda _=False, sid=person.id: self._hire(sid))
            layout.addWidget(hire_button, alignment=Qt.AlignmentFlag.AlignLeft)
        return frame

    def _marketing_body(self, layout: QVBoxLayout) -> None:
        state = self.state
        assert state is not None
        if state.campaign is not None:
            camp = state.campaign
            who = ""
            if camp.staff_id:
                person = next((member for member in state.staff if member.id == camp.staff_id), None)
                who = f" Face: {person.name}." if person else ""
            layout.addWidget(_wrap(
                f"Running: {camp.kind.replace('_', ' ')}, {camp.tone}, {CATEGORY_LABELS.get(camp.category, camp.category)}. "
                f"{camp.days_left} days left.{who}",
                "cardTitle",
            ))
        else:
            layout.addWidget(_wrap("No campaign running. One at a time.", "quiet"))
        self._campaign_kind = QComboBox()
        for key, label, cost in (
            ("social", "Social post", 70),
            ("email", "Email", 150),
            ("local_ad", "Local ad", 400),
            ("influencer", "Influencer", 980),
        ):
            self._campaign_kind.addItem(f"{label} · {money(cost)}", key)
        self._campaign_tone = QComboBox()
        for key, label in (("discreet", "Discreet"), ("playful", "Playful"), ("bold", "Bold")):
            self._campaign_tone.addItem(label, key)
        self._campaign_category = QComboBox()
        for key in CATEGORIES:
            self._campaign_category.addItem(CATEGORY_LABELS[key], key)
        self._campaign_staff = QComboBox()
        self._campaign_staff.addItem("No face", "")
        for person in state.staff:
            if person.employed:
                self._campaign_staff.addItem(person.name, person.id)
        form = QHBoxLayout()
        for widget in (self._campaign_kind, self._campaign_tone, self._campaign_category, self._campaign_staff):
            form.addWidget(widget)
        if state.mode == "corporate":
            self._campaign_door = QComboBox()
            self._campaign_door.addItem("Every city", "")
            for door in state.doors:
                self._campaign_door.addItem(door.city, door.id)
            form.addWidget(self._campaign_door)
        launch = QPushButton("Launch")
        launch.clicked.connect(self._launch)
        form.addWidget(launch)
        layout.addLayout(form)
        if state.mode == "corporate":
            layout.addWidget(_wrap(
                "Every city multiplies the fee by the number of doors. One city pays the list price. "
                f"Co-op accrued is {money(coop_claimable(state))}. It comes off the bill when the ad is accepted. "
                "The manager still writes the floor.",
                "quiet",
            ))
        else:
            layout.addWidget(_wrap(
                "A bold local ad or influencer post can be rejected. The fee is already gone. Social posts put that person on the camera today.",
                "quiet",
            ))
        if state.mode == "corporate":
            return
        layout.addWidget(_wrap("Tonight", "section"))
        if not any(site.is_physical for site in state.sites):
            layout.addWidget(_wrap("Events need a room. The online counter does not have one.", "quiet"))
            return
        if state.scheduled_event is not None:
            event = state.scheduled_event
            host = next((person.name for person in state.staff if person.id == event.host_id), "nobody")
            rules = "rules posted" if event.strict_rules else "loose"
            layout.addWidget(_wrap(
                f"Booked: {event.kind.replace('_', ' ')} with {host}, {rules}, featuring {CATEGORY_LABELS.get(event.category, event.category)}.",
            ))
            clear = QPushButton("Take the night off the book")
            clear.setObjectName("quiet")
            clear.clicked.connect(self._cancel_event)
            layout.addWidget(clear, alignment=Qt.AlignmentFlag.AlignLeft)
            return
        self._event_kind = QComboBox()
        for key, label in (("try_on", "After-hours try-on"), ("demo", "Product demo"), ("couples", "Couples night")):
            self._event_kind.addItem(label, key)
        self._event_category = QComboBox()
        for key in CATEGORIES:
            self._event_category.addItem(CATEGORY_LABELS[key], key)
        self._event_host = QComboBox()
        for person in state.staff:
            if person.employed:
                self._event_host.addItem(person.name, person.id)
        self._event_rules = QCheckBox("Post the rules at the door")
        self._event_rules.setChecked(True)
        row = QHBoxLayout()
        row.addWidget(self._event_kind)
        row.addWidget(self._event_category)
        row.addWidget(self._event_host)
        book = QPushButton("Book tonight")
        book.clicked.connect(self._book)
        row.addWidget(book)
        layout.addLayout(row)
        layout.addWidget(self._event_rules)
        layout.addWidget(_wrap("A willing host and posted rules keep the night a high-margin shift instead of a note you will regret.", "quiet"))

    def _customers_body(self, layout: QVBoxLayout) -> None:
        state = self.state
        assert state is not None
        layout.addWidget(_wrap("Regulars remember stockouts, a quiet room, and a push you allowed.", "quiet"))
        for person in state.regulars:
            frame, inner = _card()
            status = "In the book" if person.introduced and person.active else "Not coming back" if not person.active else "Not in yet"
            inner.addWidget(_wrap(f"{person.name} · {status}", "cardTitle"))
            inner.addWidget(_wrap(person.blurb))
            prefs = ", ".join(CATEGORY_LABELS.get(key, key) for key in person.preferences)
            inner.addWidget(_wrap(
                f"Wants {prefs}. Loyalty {person.loyalty} · spent {money(person.spend)} · "
                f"discretion {person.discretion} · push {person.pushiness}. Visits {person.visits}.",
                "quiet",
            ))
            layout.addWidget(frame)

    def _manager_card(self, person) -> QFrame:
        state = self.state
        assert state is not None
        frame, layout = _card()
        where = next((door.city for door in state.doors if door.id == person.door_id), "Unassigned")
        status = f"{where} · {money(person.wage)} / week" if person.employed else f"Available · {money(person.wage)} / week"
        layout.addWidget(_wrap(f"{person.name} · {status}", "cardTitle"))
        layout.addWidget(_wrap(person.short))
        layout.addWidget(_chips([
            ("Floor", str(person.operations)),
            ("Wall", str(person.merchandising)),
            ("People", str(person.leadership)),
            ("City", str(person.local_sense)),
        ]))
        if not person.employed:
            button = QPushButton(f"Hire · {money(person.wage)} / week")
            button.clicked.connect(lambda _=False, mid=person.id: self._hire_manager(mid))
            layout.addWidget(button, alignment=Qt.AlignmentFlag.AlignLeft)
            return frame
        row = QHBoxLayout()
        combo = QComboBox()
        for door in state.doors:
            combo.addItem(door.city, door.id)
        combo.setCurrentIndex(max(0, combo.findData(person.door_id)))
        button = QPushButton("Give them this door")
        button.clicked.connect(lambda _=False, mid=person.id, box=combo: self._give_door(mid, box))
        row.addWidget(combo, stretch=1)
        row.addWidget(button)
        layout.addLayout(row)
        return frame

    def _stores_body(self, layout: QVBoxLayout) -> None:
        state = self.state
        assert state is not None
        warehouse = sum(line.on_hand for line in state.stock.values())
        layout.addWidget(_wrap(
            f"Drawer {money(state.cash)}. Warehouse {warehouse} units in Evansville. "
            f"Sunday needs about {money(weekly_obligations(state))}. "
            "You buy once. Trucks leave Evansville and take longer the farther the city is. "
            "A new lease does not sell until zoning and the build-out are done. "
            "Managers spend the labor budget. Co-op accrues when you buy and comes off an ad when you claim it.",
            "quiet",
        ))
        self._plano = {}
        self._truck_product = {}
        self._truck_qty = {}
        self._door_open = {}
        self._door_close = {}
        self._labor = {}
        self._weeks = {}
        for door in state.doors:
            frame, inner = _card()
            manager = next((person.name for person in state.managers if person.id == door.manager_id), "No manager")
            intense = "Pharmacy counter allowed." if door.allows_intense else "The lease keeps the pharmacy counter off."
            schedule = "Posted schedule. A change after Monday costs predictability pay." if door.fair_workweek else "The roster locks after Monday."
            if door.status == "buildout":
                phase = f"Build-out. Opens day {door.opens_on}. Rent is already running."
            else:
                phase = "Open."
            inner.addWidget(_wrap(f"{door.city}, {door.state_name}", "cardTitle"))
            inner.addWidget(_wrap(
                f"{phase} {door.region}. {manager}. Rent {money(door.rent_weekly)} / week. "
                f"Sales tax {door.sales_tax_bps / 100:.2f}%".replace(".00%", "%")
                + f". Wage floor {money(door.wage_floor)}. Truck {door.transit_days} days. {intense} {schedule}",
            ))
            inner.addWidget(_wrap(door.blurb, "quiet"))
            inner.addWidget(_wrap(
                f"Yesterday {money(door.last_sales)}. Week sales {money(door.week_sales)}. "
                f"Last contribution {money(door.last_contribution)}. Wall match {door.compliance}. "
                f"Open {door.open_hour}:00–{door.close_hour}:00. Freight {money(door.freight_per_unit)} a unit. "
                f"Labor budget {money(door.labor_budget)}. Cover {door.weeks_of_supply} weeks.",
                "quiet",
            ))
            trucks = [item for item in state.shipments if item.door_id == door.id]
            if trucks:
                inner.addWidget(_wrap(
                    "On the road: " + "; ".join(
                        f"{sum(item.lines.values())} units arrive day {item.arrives_on}" for item in trucks
                    ),
                    "hint",
                ))
            hours = QHBoxLayout()
            open_spin = QSpinBox()
            open_spin.setRange(8, 18)
            open_spin.setValue(door.open_hour)
            close_spin = QSpinBox()
            close_spin.setRange(12, 23)
            close_spin.setValue(door.close_hour)
            self._door_open[door.id] = open_spin
            self._door_close[door.id] = close_spin
            post = QPushButton("Post hours")
            post.clicked.connect(lambda _=False, door_id=door.id: self._post_city_hours(door_id))
            hours.addWidget(_wrap("Open", "quiet"))
            hours.addWidget(open_spin)
            hours.addWidget(_wrap("Close", "quiet"))
            hours.addWidget(close_spin)
            hours.addWidget(post)
            hours.addStretch(1)
            inner.addLayout(hours)
            budget = QHBoxLayout()
            labor = QSpinBox()
            labor.setObjectName("storesLaborBudget")
            labor.setRange(400, labor_budget_ceiling(door.labor_budget))
            labor.setSingleStep(50)
            labor.setValue(door.labor_budget)
            weeks = QSpinBox()
            weeks.setRange(1, 8)
            weeks.setValue(door.weeks_of_supply)
            self._labor[door.id] = labor
            self._weeks[door.id] = weeks
            budget.addWidget(_wrap("Labor budget", "quiet"))
            budget.addWidget(labor)
            budget.addWidget(_wrap("Weeks of supply", "quiet"))
            budget.addWidget(weeks)
            save_budget = QPushButton("Set budget")
            save_budget.clicked.connect(lambda _=False, door_id=door.id: self._set_budget(door_id))
            budget.addWidget(save_budget)
            budget.addStretch(1)
            inner.addLayout(budget)
            inner.addWidget(_wrap("Planogram. The shares have to add up to 100.", "hint"))
            grid = QHBoxLayout()
            spins = {}
            for key in CATEGORIES:
                column = QVBoxLayout()
                column.addWidget(_wrap(CATEGORY_SHORT.get(key, key), "quiet"))
                spin = QSpinBox()
                spin.setRange(0, 100)
                spin.setValue(int(door.planogram.get(key, 0)))
                spins[key] = spin
                column.addWidget(spin)
                grid.addLayout(column)
            self._plano[door.id] = spins
            inner.addLayout(grid)
            send = QPushButton("Send this wall")
            send.clicked.connect(lambda _=False, door_id=door.id: self._send_wall(door_id))
            inner.addWidget(send, alignment=Qt.AlignmentFlag.AlignLeft)
            truck = QHBoxLayout()
            product = QComboBox()
            product.addItem("Pick from the warehouse", "")
            for product_id, line in state.stock.items():
                if line.on_hand <= 0:
                    continue
                item = state.products[product_id]
                product.addItem(f"{item.name} · {line.on_hand}", product_id)
            qty = QSpinBox()
            qty.setRange(1, order_qty_max())
            qty.setValue(min(2, order_qty_max()))
            qty.setMinimumWidth(84)
            self._truck_product[door.id] = product
            self._truck_qty[door.id] = qty
            go = QPushButton("Send the truck")
            go.clicked.connect(lambda _=False, door_id=door.id: self._send_truck(door_id))
            fill = QPushButton("Replenish")
            fill.clicked.connect(lambda _=False, door_id=door.id: self._replenish(door_id))
            truck.addWidget(product, stretch=1)
            truck.addWidget(qty)
            truck.addWidget(go)
            truck.addWidget(fill)
            inner.addLayout(truck)
            layout.addWidget(frame)
        layout.addWidget(_wrap("Cities still on the list", "section"))
        available = openable_markets(state)
        if not available:
            layout.addWidget(_wrap("Every city on this list is already leased.", "quiet"))
        for market in available:
            frame, inner = _card()
            inner.addWidget(_wrap(f"{market.city}, {market.state_name}", "cardTitle"))
            inner.addWidget(_wrap(market.blurb))
            inner.addWidget(_wrap(
                f"Opening {money(market.opening_cost)}. Rent {money(market.rent_weekly)} / week. "
                f"Build-out {market.build_days} days before the first sale. "
                f"The truck takes {market.transit_days} days. "
                f"Leave at least {money(market.min_cash_after)} in the drawer.",
                "quiet",
            ))
            button = QPushButton(f"Sign {market.city}")
            button.clicked.connect(lambda _=False, market_id=market.id: self._sign_city(market_id))
            inner.addWidget(button, alignment=Qt.AlignmentFlag.AlignLeft)
            layout.addWidget(frame)
        layout.addWidget(_wrap("Houses", "section"))
        layout.addWidget(_wrap(
            "List price until the chain has two doors or $1,200 with that house. "
            "The next tier is 4% off and net 30. Four doors, or $4,000 with the house, is 8% off. "
            "Co-op accrues on the receipts and is spent when you launch an ad. "
            "A piece that sits 28 days is marked down 20% once.",
            "quiet",
        ))
        for supplier in SUPPLIERS.values():
            if supplier.id == "labelco" and not state.flags.private_label:
                continue
            account = next((item for item in state.supplier_accounts if item.supplier_id == supplier.id), None)
            deal = next((item for item in state.deals if item.supplier_id == supplier.id), None)
            volume = account.volume if account else 0
            standing = (
                f"{deal.tier}, {deal.cost_off_percent}% off, co-op accrued {money(deal.coop_accrued)}"
                if deal else "list price"
            )
            row = QHBoxLayout()
            row.addWidget(_wrap(f"{supplier.name} · {standing} · bought {money(volume)}", "quiet"), stretch=1)
            button = QPushButton("Sign the deal")
            button.clicked.connect(lambda _=False, supplier_id=supplier.id: self._sign_house(supplier_id))
            row.addWidget(button)
            layout.addLayout(row)

    def _hire_manager(self, manager_id: str) -> None:
        if self.state is None:
            return
        self._say(hire_manager(self.state, manager_id))
        self._save()
        self.refresh()

    def _give_door(self, manager_id: str, combo: QComboBox) -> None:
        if self.state is None:
            return
        self._say(assign_manager(self.state, manager_id, str(combo.currentData() or "")))
        self._save()
        self.refresh()

    def _place_staff(self, staff_id: str, combo: QComboBox) -> None:
        if self.state is None:
            return
        door_id = str(combo.currentData() or "")
        if not door_id:
            person = next((item for item in self.state.staff if item.id == staff_id), None)
            if person is not None:
                person.door_id = ""
            self._say("They are off a door.")
        else:
            self._say(assign_door(self.state, staff_id, door_id))
        self._save()
        self.refresh()

    def _send_wall(self, door_id: str) -> None:
        if self.state is None:
            return
        spins = self._plano.get(door_id, {})
        shares = {key: spin.value() for key, spin in spins.items()}
        text = set_planogram(self.state, door_id, shares)
        door = next((item for item in self.state.doors if item.id == door_id), None)
        city = door.city if door else "the store"
        self._say(text or f"The wall for {city} adds up. The manager has to catch up to it.")
        self._save()
        self.refresh()

    def _set_budget(self, door_id: str) -> None:
        if self.state is None:
            return
        door = next((item for item in self.state.doors if item.id == door_id), None)
        labor = self._labor.get(door_id)
        weeks = self._weeks.get(door_id)
        if door is None or labor is None or weeks is None:
            return
        door.labor_budget = labor.value()
        door.weeks_of_supply = weeks.value()
        door.roster_set = False
        self._say(
            f"{door.city} labor budget is {money(door.labor_budget)} a week. "
            f"Replenishment covers {door.weeks_of_supply} weeks of the last week's sales. "
            "The manager rewrites the roster on the next close."
        )
        self._save()
        self.refresh()

    def _replenish(self, door_id: str) -> None:
        if self.state is None:
            return
        self._say(replenish(self.state, door_id))
        self._save()
        self.refresh()

    def _send_truck(self, door_id: str) -> None:
        if self.state is None:
            return
        product = self._truck_product.get(door_id)
        qty = self._truck_qty.get(door_id)
        if product is None or qty is None or not product.currentData():
            self._say("Pick something the warehouse actually has.")
            return
        self._say(allocate(self.state, door_id, {str(product.currentData()): qty.value()}))
        self._save()
        self.refresh()

    def _post_city_hours(self, door_id: str) -> None:
        if self.state is None:
            return
        open_spin = self._door_open.get(door_id)
        close_spin = self._door_close.get(door_id)
        if open_spin is None or close_spin is None:
            return
        self._say(set_door_hours(self.state, door_id, open_spin.value(), close_spin.value()))
        self._save()
        self.refresh()

    def _sign_city(self, market_id: str) -> None:
        if self.state is None:
            return
        self._say(open_market(self.state, market_id))
        self._save()
        self.refresh()

    def _sign_house(self, supplier_id: str) -> None:
        if self.state is None:
            return
        self._say(sign_deal(self.state, supplier_id))
        self._save()
        self.refresh()


    def _offer_card(self, state, offer) -> QFrame:
        """Site-offer card in the same Store Portfolio style."""
        frame = QFrame()
        frame.setObjectName("storeCard")
        frame.setProperty("offerId", offer.id)
        frame.setFixedWidth(220)
        box = QVBoxLayout(frame)
        box.setContentsMargins(0, 0, 0, 10)
        box.setSpacing(4)
        art = StorefrontArt(resolved_chain_id(state), frame)
        art.set_chain(resolved_chain_id(state), open_badge=False, hero=False)
        box.addWidget(art)
        pad = QVBoxLayout()
        pad.setContentsMargins(12, 4, 12, 0)
        pad.setSpacing(4)
        title = QLabel(offer.label)
        title.setObjectName("offerTitle")
        title.setFont(ui_font(14, QFont.Weight.DemiBold))
        title.setStyleSheet(f"color: {HQ_TITLE}; background: transparent;")
        title.setWordWrap(True)
        pad.addWidget(title)
        blurb = QLabel(offer.blurb)
        blurb.setObjectName("offerBlurb")
        blurb.setFont(ui_font(11))
        blurb.setStyleSheet(f"color: {HQ_MUTED}; background: transparent;")
        blurb.setWordWrap(True)
        pad.addWidget(blurb)
        needs = []
        if offer.min_respectable:
            needs.append(f"respectable {offer.min_respectable}")
        if offer.min_nightlife:
            needs.append(f"nightlife {offer.min_nightlife}")
        if offer.needs_online:
            needs.append("online already open")
        need_text = (" Needs " + ", ".join(needs) + ".") if needs else ""
        opening = QLabel(f"Opening  {money_compact(offer.opening_cost)}")
        opening.setObjectName("offerOpening")
        opening.setFont(ui_font(12))
        opening.setStyleSheet(f"color: {HQ_TITLE}; background: transparent;")
        opening.setToolTip(money(offer.opening_cost))
        pad.addWidget(opening)
        rent = QLabel(f"Rent  {money_compact(offer.rent_weekly)} / week")
        rent.setObjectName("offerRent")
        rent.setFont(ui_font(12))
        rent.setStyleSheet(f"color: {HQ_TITLE}; background: transparent;")
        rent.setToolTip(money(offer.rent_weekly) + " / week")
        pad.addWidget(rent)
        reserve = QLabel(f"Leave at least {money_compact(offer.min_cash_after)} in the drawer.{need_text}")
        reserve.setObjectName("offerReserve")
        reserve.setFont(ui_font(11))
        reserve.setStyleSheet(f"color: {HQ_MUTED}; background: transparent;")
        reserve.setWordWrap(True)
        reserve.setToolTip(money(offer.min_cash_after))
        pad.addWidget(reserve)
        sign = QPushButton(f"Sign for {offer.label}")
        sign.setObjectName("signLease")
        sign.setProperty("offerKey", offer.id)
        sign.setMinimumHeight(36)
        sign.clicked.connect(lambda _=False, key=offer.id: self._open_site(key))
        pad.addWidget(sign)
        box.addLayout(pad)
        return frame

    def _expansion_body(self, layout: QVBoxLayout) -> None:
        state = self.state
        assert state is not None
        if state.mode == "corporate":
            self._stores_body(layout)
            return
        layout.addWidget(_wrap("Expansion", "section"))
        layout.addWidget(_wrap(
            f"Drawer {money(state.cash)}. Sunday needs about {money(weekly_obligations(state))}. "
            "Opening costs come out of the drawer, and then the rent does too.",
            "quiet",
        ))
        if state.sites:
            layout.addWidget(_wrap("Open now", "section"))
            for site in state.sites:
                kind = "Warehouse" if site.is_warehouse else "Shop"
                intense = "Pharmacy product can sell here." if site.allows_intense else "The lease keeps the pharmacy counter off the fixture."
                layout.addWidget(_wrap(f"{site.label} · {kind} · rent {money(site.rent_weekly)} / week. {intense}"))
        if state.credit_used:
            row = QHBoxLayout()
            self._repay_spin = QSpinBox()
            self._repay_spin.setRange(1, max(1, state.credit_used))
            self._repay_spin.setValue(min(500, state.credit_used))
            pay = QPushButton("Pay the line")
            pay.clicked.connect(self._repay)
            row.addWidget(self._repay_spin)
            row.addWidget(pay)
            row.addWidget(_wrap(f"Balance {money(state.credit_used)}. Interest is 2% on Sunday.", "quiet"))
            row.addStretch(1)
            layout.addLayout(row)
        else:
            layout.addWidget(_wrap(f"Credit line {money(state.credit_limit)}, unused. It covers a bad Sunday. It does not pay a supplier.", "quiet"))
        layout.addWidget(_wrap("Next", "section"))
        if not state.flags.online_open:
            button = QPushButton(f"Open the online counter · {money(ONLINE_SETUP_COST)}")
            button.clicked.connect(self._online)
            layout.addWidget(button, alignment=Qt.AlignmentFlag.AlignLeft)
            layout.addWidget(_wrap("A plain site. Someone still has to pack.", "quiet"))
        if not state.flags.private_label:
            button = QPushButton(f"Pay for a house label · {money(LABEL_SETUP_COST)}")
            button.clicked.connect(self._label)
            layout.addWidget(button, alignment=Qt.AlignmentFlag.AlignLeft)
            layout.addWidget(_wrap(
                f"Private Label Co wants day {LABEL_MIN_DAY} and {LABEL_MIN_REP} on either reputation. Then you can order the Retail Rivals house brand and the House Line staples.",
                "quiet",
            ))
        grid = QGridLayout()
        grid.setSpacing(12)
        grid.setContentsMargins(0, 8, 0, 0)
        offers = list(spendable_offers(state))
        # Two columns so the cards stay fully visible at 1100px as well as 1366px.
        for index, offer in enumerate(offers):
            grid.addWidget(self._offer_card(state, offer), index // 2, index % 2)
        layout.addLayout(grid)

    def _journal_body(self, layout: QVBoxLayout) -> None:
        state = self.state
        assert state is not None
        pending = [message for message in state.inbox if not message.resolved]
        pending.sort(key=lambda message: (not message.urgent, -message.day))
        if pending:
            layout.addWidget(_wrap("Needs an answer", "section"))
            for message in pending:
                layout.addWidget(self._message_card(message))
        if not state.journal:
            if not pending:
                layout.addWidget(_wrap("The journal starts when you close a day.", "quiet"))
            return
        layout.addWidget(_wrap("Closed days", "section"))
        for entry in reversed(state.journal[-12:]):
            frame, inner = _card()
            inner.addWidget(_wrap(entry))
            layout.addWidget(frame)

    def _books_body(self, layout: QVBoxLayout) -> None:
        state = self.state
        assert state is not None
        columns = QHBoxLayout()
        columns.setSpacing(12)
        columns.addWidget(_statement("This quarter", income_lines(state), {"Gross profit", "Quarter net"}), stretch=1)
        columns.addWidget(_statement("What you hold", balance_lines(state), {"Assets", "Liabilities", "Equity"}), stretch=1)
        layout.addLayout(columns)
        chart = self._cash_chart()
        if chart is not None:
            layout.addWidget(chart)
        layout.addWidget(_wrap(
            f"Gross margin {format_margin(state.quarter_sales, state.quarter_refunds, state.quarter_cogs)}. "
            f"Sales tax is collected on top of the price and is not in these sales. "
            f"Card fees are 2.6% of what the customer was charged. A profitable quarter pays 21% income tax when it closes.",
            "quiet",
        ))
        runway = _wrap(_compact_money_in_text(describe_runway(state)))
        runway.setToolTip(describe_runway(state))
        layout.addWidget(runway)
        tax_line = _wrap(
            f"Sales tax held {money_compact(state.tax_held)}. Remitted so far {money_compact(state.tax_lifetime)}. "
            f"Fixtures net {money_compact(fixtures_net(state))}. Owner draws {money_compact(state.owner_draws)}.",
            "quiet",
        )
        tax_line.setToolTip(
            f"Sales tax held {money(state.tax_held)}. Remitted so far {money(state.tax_lifetime)}. "
            f"Fixtures net {money(fixtures_net(state))}. Owner draws {money(state.owner_draws)}."
        )
        layout.addWidget(tax_line)
        owed = [account for account in state.supplier_accounts if account.payable > 0]
        if owed:
            layout.addWidget(_wrap("Open supplier bills", "section"))
            for account in owed:
                supplier = SUPPLIERS.get(account.supplier_id)
                name = supplier.name if supplier else account.supplier_id
                bill = _wrap(
                    f"{name}: {money_compact(account.payable)}, due day {account.due_day}, late {account.late_payments}.",
                    "quiet",
                )
                bill.setToolTip(
                    f"{name}: {money(account.payable)}, due day {account.due_day}, late {account.late_payments}."
                )
                layout.addWidget(bill)
        if state.months:
            layout.addWidget(_wrap("Closed quarters", "section"))
            for statement in reversed(state.months[-4:]):
                closed = _wrap(
                    f"Day {statement.day}: net {money_compact(statement.net)} on sales {money_compact(statement.sales)}. "
                    f"{_compact_money_in_text(statement.note)}",
                    "quiet",
                )
                closed.setToolTip(
                    f"Day {statement.day}: net {money(statement.net)} on sales {money(statement.sales)}. {statement.note}"
                )
                layout.addWidget(closed)
        draw_row = QHBoxLayout()
        self._draw_spin = QSpinBox()
        self._draw_spin.setRange(50, max(50, state.cash))
        self._draw_spin.setSingleStep(50)
        self._draw_spin.setValue(min(200, max(50, state.cash)))
        self._draw_spin.setPrefix("$")
        if hasattr(self._draw_spin, "setGroupSeparatorShown"):
            self._draw_spin.setGroupSeparatorShown(True)
        self._draw_spin.setMinimumWidth(120)
        draw = QPushButton("Take an owner draw")
        draw.setObjectName("quiet")
        draw.clicked.connect(self._draw)
        draw_row.addWidget(self._draw_spin)
        draw_row.addWidget(draw)
        draw_row.addStretch(1)
        layout.addLayout(draw_row)
        layout.addWidget(_wrap("A draw is yours. It is not an expense, and it will not pay Sunday.", "hint"))

    def _operations_body(self, layout: QVBoxLayout) -> None:
        state = self.state
        assert state is not None
        span = hours_open(state)
        if state.mode == "corporate":
            layout.addWidget(_wrap(
                "Each city posts its own hours. Seattle charges predictability pay when the schedule moves after Monday. "
                "Eight hours is straight time. Past that, the floor is time and a half. "
                "Sunday takes rent for every door, manager salaries, wages, 7.65% employer tax, and the sales tax each city collected.",
            ))
        else:
            layout.addWidget(_wrap(
                f"Posted hours {state.open_hour}:00–{state.close_hour}:00 ({span} hours). "
                "Eight hours is straight time. Past that, wages are time and a half, and the floor burns out faster. "
                "Sunday also takes 7.65% employer tax, insurance, and utilities.",
            ))
        if state.mode == "corporate":
            self._door_open = {}
            self._door_close = {}
            for door in state.doors:
                row = QHBoxLayout()
                row.addWidget(_wrap(door.city, "quiet"))
                open_spin = QSpinBox()
                open_spin.setObjectName(f"doorOpen_{door.id}")
                open_spin.setRange(8, 18)
                open_spin.setValue(door.open_hour)
                close_spin = QSpinBox()
                close_spin.setObjectName(f"doorClose_{door.id}")
                close_spin.setRange(12, 23)
                close_spin.setValue(door.close_hour)
                self._door_open[door.id] = open_spin
                self._door_close[door.id] = close_spin
                post = QPushButton("Post hours")
                post.setObjectName(f"postHours_{door.id}")
                post.clicked.connect(lambda _=False, door_id=door.id: self._post_city_hours(door_id))
                row.addWidget(_wrap("Open", "quiet"))
                row.addWidget(open_spin)
                row.addWidget(_wrap("Close", "quiet"))
                row.addWidget(close_spin)
                row.addWidget(post)
                row.addStretch(1)
                layout.addLayout(row)
        else:
            row = QHBoxLayout()
            self._open_spin = QSpinBox()
            self._open_spin.setRange(8, 18)
            self._open_spin.setValue(state.open_hour)
            self._close_spin = QSpinBox()
            self._close_spin.setRange(12, 23)
            self._close_spin.setValue(state.close_hour)
            apply_hours = QPushButton("Post these hours")
            apply_hours.clicked.connect(self._hours)
            row.addWidget(_wrap("Open", "quiet"))
            row.addWidget(self._open_spin)
            row.addWidget(_wrap("Close", "quiet"))
            row.addWidget(self._close_spin)
            row.addWidget(apply_hours)
            row.addStretch(1)
            layout.addLayout(row)
        report = state.last_report
        if report.day:
            missed = QHBoxLayout()
            missed.setSpacing(10)
            for caption, value in (
                ("FLOOR COULD HOLD", str(report.capacity)),
                ("EMPTY SHELF", str(report.lost_stockout)),
                ("PRICE", str(report.lost_price)),
                ("COVERAGE", str(report.lost_staff)),
                ("WALKED", str(report.lost_walk)),
                ("SHRINK", money(report.shrink_cost)),
            ):
                missed.addWidget(_figure(caption, value), stretch=1)
            layout.addLayout(missed)
        layout.addWidget(_wrap("Oldest stock in the warehouse" if state.mode == "corporate" else "Oldest stock", "section"))
        rows = oldest_stock(state)
        if not rows:
            layout.addWidget(_wrap("The shelf is empty.", "quiet"))
        for name, on_hand, age, cost in rows:
            layout.addWidget(_wrap(f"{name}: {on_hand} on hand, {age} days, {money(cost)} at cost.", "quiet"))
        layout.addWidget(_wrap(
            f"About {runway_days(state)} days of Sunday bills are in the drawer if nothing else moves.",
            "hint",
        ))

    def _market_body(self, layout: QVBoxLayout) -> None:
        state = self.state
        assert state is not None
        rival = state.rival
        frame, inner = _card()
        inner.addWidget(_wrap(rival.name, "cardTitle"))
        inner.addWidget(_wrap(rival.note))
        inner.addWidget(_wrap(
            f"Price index {rival.price_index}. Their reputation {rival.reputation}. "
            f"{rival.blocks_away} blocks away. They push {rival.focus.replace('_', ' ')}.",
            "quiet",
        ))
        if state.flags.competitor < 20:
            inner.addWidget(_wrap("They are not in your traffic yet. A strong week puts them on the tape.", "hint"))
        else:
            inner.addWidget(_wrap(
                "They are pricing against you. The category they push converts a little worse while they are close.",
                "hint",
            ))
        layout.addWidget(frame)
        layout.addWidget(_wrap(
            f"Mailing list {state.list_size}. An email campaign reaches further as the list grows. It starts small.",
            "quiet",
        ))
        layout.addWidget(_wrap("Quarter marks", "section"))
        open_targets = [target for target in state.targets if not target.closed]
        closed = [target for target in state.targets if target.closed]
        if not open_targets and not closed:
            layout.addWidget(_wrap("No marks on the board yet.", "quiet"))
        for target in open_targets:
            layout.addWidget(_wrap(f"By day {target.due_day}: {target.label}.", "quiet"))
        for target in closed[-6:]:
            word = "met" if target.met else "missed"
            layout.addWidget(_wrap(f"Day {target.due_day}: {target.label} — {word}.", "quiet"))

    def _cash_chart(self) -> QWidget | None:
        state = self.state
        assert state is not None
        history = [report for report in state.history[-14:] if report.cash_end or report.day]
        if not history:
            return None
        return _MoneyBars("Drawer at close", [(str(report.day), int(report.cash_end)) for report in history], "#0B6CBD")

    def _category_chart(self) -> QWidget | None:
        state = self.state
        assert state is not None
        report = state.last_report
        if report.day == 0:
            return None
        points = [(CATEGORY_SHORT[key], int(report.by_category.get(key, 0))) for key in CATEGORIES]
        return _MoneyBars("Yesterday by category", points, "#3AA6A0")

    def _revenue_chart(self) -> QWidget | None:
        state = self.state
        assert state is not None
        history = state.history[-14:]
        if not history:
            return None
        return _SalesCurve([(str(report.day), report.revenue) for report in history])

    def _chart(self, title: str) -> QChart:
        chart = QChart()
        chart.setTitle(title)
        chart.setBackgroundBrush(QColor("#F4F6FA"))
        chart.setPlotAreaBackgroundBrush(QColor("#F4F6FA"))
        chart.setPlotAreaBackgroundVisible(True)
        chart.setTitleBrush(QColor("#1A1A1A"))
        chart.setMargins(QMargins(8, 8, 8, 8))
        chart.legend().setVisible(False)
        chart.setAnimationOptions(QChart.AnimationOption.NoAnimation)
        title_font = QFont("Selawik")
        title_font.setPixelSize(13)
        chart.setTitleFont(title_font)
        return chart

    def _paint_axes(self, chart: QChart, series, axis_x, axis_y) -> None:
        for axis in (axis_x, axis_y):
            axis.setLabelsBrush(QColor("#5C5C5C"))
            axis.setGridLineColor(QColor("#E4E7EC"))
            chart.addAxis(axis, Qt.AlignmentFlag.AlignBottom if axis is axis_x else Qt.AlignmentFlag.AlignLeft)
            series.attachAxis(axis)

    def _chart_view(self, chart: QChart) -> QChartView:
        view = QChartView(chart)
        view.setMinimumHeight(240)
        view.setMaximumHeight(280)
        view.setStyleSheet("background: #F4F6FA; border: none;")
        return view

    def _say(self, text: str) -> None:
        self.status.setText(text)
        note = getattr(self, "sidebar_note", None)
        if note is not None and note is not self.status:
            note.setText(text)
        if self.desktop is None:
            return
        self.status.setWordWrap(True)
        self.status.setVisible(bool(text))
        if text:
            self.status.setStyleSheet(
                "QLabel#status { background: rgba(255,255,255,230); color: #1A1A1A; "
                "border: 1px solid rgba(0,0,0,40); border-radius: 8px; padding: 8px 12px; }"
            )
            self.status.adjustSize()
            width = min(520, max(280, self.desktop.width() - 40))
            self.status.setFixedWidth(width)
            self.status.adjustSize()
            rail = getattr(self.desktop, "rail", None)
            topbar = getattr(self.desktop, "topbar", None)
            left = (rail.width() if rail is not None else 0) + 16
            # Sit in the lower work area so the toast does not cover the first
            # Inventory row (supplier combo) or other page headers.
            body = getattr(self.desktop, "body", None)
            work_bottom = self.desktop.height() - 16
            if body is not None:
                work_bottom = body.mapTo(self.desktop, body.rect().bottomLeft()).y() - 16
            top = max(
                (topbar.height() if topbar is not None else 48) + 8,
                work_bottom - self.status.height(),
            )
            self.status.move(left, top)
            self.status.raise_()

    def _save(self) -> None:
        if self.state is not None:
            self.store.save(self.state)

    def _help(self) -> None:
        from open_late.ui.desktop import AppWindow

        if self.desktop is not None and self.stack.currentWidget() is self.play_page:
            self._open_app("help")
            return
        page = self.stack.currentWidget()
        win = getattr(self, "_help_window", None)
        if win is None or win.parent() is not page:
            if win is not None:
                win.hide()
                win.setParent(None)
                win.deleteLater()
            win = AppWindow("help", "How the desk works", page)
            self._help_window = win
        fill_help_window(win)
        width, height = page.width(), page.height()
        ww = min(720, max(520, width - 80))
        hh = min(600, max(420, height - 80))
        win.setGeometry(max(20, (width - ww) // 2), max(20, (height - hh) // 2), ww, hh)
        win.show()
        win.lift()

    def _front(self) -> None:
        self.state = None
        self._say("")
        self.refresh()

    def _show_setup(self) -> None:
        if self.state is not None:
            answer_box = QMessageBox.question(
                self,
                "New shop",
                "Leave this day? It is already saved if you closed or changed anything since the last save.",
            )
            if answer_box != QMessageBox.StandardButton.Yes:
                return
        self.state = None
        self.stack.setCurrentWidget(self.setup_page)
        self._sync_start()

    def _sync_start(self) -> None:
        ready = self.age_check.isChecked() and bool(self.name_input.text().strip())
        self.start_button.setEnabled(ready)

    def _start(self) -> None:
        if not self.age_check.isChecked():
            return
        if self.corporate_radio.isChecked():
            mode = "corporate"
        elif self.shop_radio.isChecked():
            mode = "shop"
        else:
            mode = "online"
        from open_late.ui.hq_adapter import default_chain_id, set_chain
        chain_id = self._chosen_chain_id or default_chain_id()
        difficulty = getattr(self, "_chosen_economy", None) or "standard"
        name = self.name_input.text().strip() or "Retail Rivals"
        try:
            self.state = new_game(name, mode, chain_id=chain_id, economy_difficulty=difficulty)
        except TypeError:
            try:
                self.state = new_game(name, mode, chain_id=chain_id)
            except TypeError:
                self.state = new_game(name, mode)
                try:
                    set_chain(self.state, chain_id)
                except Exception:
                    pass
            try:
                from open_late.economy import configure_new_game
                configure_new_game(self.state, difficulty)
            except Exception:
                pass
        self._save()
        self._say("")
        self.refresh()

    def _load(self, slot: str) -> None:
        try:
            self.state = self.store.load(slot)
        except KeyError:
            self._say("That save is gone.")
            self.refresh()
            return
        self._say("")
        self.refresh()

    def _delete(self, slot: str, name: str) -> None:
        answer_box = QMessageBox.question(self, "Delete save", f"Delete {name}? The days on that tape go with it.")
        if answer_box != QMessageBox.StandardButton.Yes:
            return
        self.store.delete(slot)
        if self.state is not None and self.state.slot == slot:
            self.state = None
        self.refresh()

    def _choose(self, message_id: str, choice_id: str) -> None:
        if self.state is None:
            return
        self._say(answer(self.state, message_id, choice_id))
        self._save()
        self.refresh()

    def _to_desk(self) -> None:
        if self.state is None:
            return
        open_desk(self.state)
        self._save()
        self._say("")
        self.refresh()

    def _close(self) -> None:
        if self.state is None:
            return
        text = close_day(self.state)
        if text:
            self._say(text)
            return
        self._desk_index = 0
        self._save()
        self._say("")
        self.refresh()

    def _next(self) -> None:
        if self.state is None:
            return
        if self.state.failed:
            self._front()
            return
        continue_morning(self.state)
        self._save()
        self._say("")
        self.refresh()

    def _priced(self, product_id: str, value: int) -> None:
        if self.state is None:
            return
        text = set_price(self.state, product_id, value)
        if text:
            self._say(text)
            return
        self._save()
        self._render_header()


    def _product_dept(self, product) -> str:
        return str(getattr(product, "department", "") or getattr(product, "category", "") or "")

    def _inventory_products(self, state) -> list:
        query = (self._inv_query or "").strip().lower()
        products = [product for product in state.products.values() if product.supplier_id == self._supplier_id]
        if self._inv_dept:
            products = [product for product in products if self._product_dept(product) == self._inv_dept]
        if query:
            kept = []
            for product in products:
                dept = self._product_dept(product)
                blob = " ".join(
                    str(part)
                    for part in (
                        product.name,
                        product.id,
                        getattr(product, "brand", ""),
                        dept,
                        CATEGORY_LABELS.get(dept, ""),
                    )
                    if part
                ).lower()
                if query in blob:
                    kept.append(product)
            products = kept
        products.sort(key=lambda product: (self._product_dept(product), product.name))
        return products

    def _inv_search_changed(self, text: str) -> None:
        self._inv_query = text
        self._inv_page = 0
        self._reload_inventory()

    def _inv_dept_changed(self, _index: int) -> None:
        combo = self.sender()
        if isinstance(combo, QComboBox):
            self._inv_dept = str(combo.currentData() or "")
        self._inv_page = 0
        self._reload_inventory()

    def _inv_step_page(self, delta: int) -> None:
        self._inv_page += delta
        self._reload_inventory()

    def _inv_qty_changed(self, product_id: str, value: int) -> None:
        self._order_qtys[product_id] = int(value)

    def _reload_inventory(self) -> None:
        if self.state is None:
            return
        self._fill_legacy("inventory")

    def _supplier_changed(self, _index: int) -> None:
        combo = self.sender()
        if isinstance(combo, QComboBox) and combo.currentData():
            self._supplier_id = str(combo.currentData())
        self._inv_page = 0
        self._inv_dept = ""
        self._order_qtys = {}
        self.refresh()

    def _suggest(self) -> None:
        if self.state is None:
            return
        filled = suggested_restock_quantities(self.state, self._supplier_id)
        for product_id, qty in filled.items():
            self._order_qtys[product_id] = int(qty)
        for product_id, spin in self._order_spins.items():
            spin.setValue(int(self._order_qtys.get(product_id, 0)))
        self._say("Quantities filled. Nothing is ordered until you place it.")

    def _terms(self, supplier_id: str, terms: str) -> None:
        if self.state is None:
            return
        self._say(set_supplier_terms(self.state, supplier_id, terms))
        self._save()
        self.refresh()

    def _raise(self, staff_id: str) -> None:
        if self.state is None:
            return
        self._say(offer_raise(self.state, staff_id))
        self._save()
        self.refresh()

    def _hours(self) -> None:
        if self.state is None:
            return
        self._say(set_hours(self.state, self._open_spin.value(), self._close_spin.value()))
        self._save()
        self.refresh()

    def _draw(self) -> None:
        if self.state is None:
            return
        self._say(owner_draw(self.state, self._draw_spin.value()))
        self._save()
        self.refresh()

    def _place(self) -> None:
        if self.state is None:
            return
        for product_id, spin in self._order_spins.items():
            self._order_qtys[product_id] = spin.value()
        quantities = {product_id: qty for product_id, qty in self._order_qtys.items() if qty > 0}
        text = place_order(self.state, self._supplier_id, quantities)
        self._say(text)
        if text.startswith("Order placed"):
            self._save()
            self.refresh()

    def _policy(self, policy: str) -> None:
        if self.state is None:
            return
        self._say(set_policy(self.state, policy))
        self._save()
        self.refresh()

    def _assign(self, staff_id: str, combo: QComboBox, hint: QLabel) -> None:
        if self.state is None:
            return
        text = set_assignment(self.state, staff_id, str(combo.currentData()))
        extra = text.removeprefix("Shift set.").strip()
        hint.setText(extra)
        if text.startswith("Shift set."):
            self._save()
        else:
            self._say(text)

    def _hire(self, staff_id: str) -> None:
        if self.state is None:
            return
        self._say(hire(self.state, staff_id))
        self._save()
        self.refresh()

    def _release(self, staff_id: str, name: str, wage: int) -> None:
        if self.state is None:
            return
        answer_box = QMessageBox.question(
            self,
            "Let them go",
            f"{name} leaves the sheet. Severance is a week's wage, {money(wage)}, if the drawer has it.",
        )
        if answer_box != QMessageBox.StandardButton.Yes:
            return
        self._say(release(self.state, staff_id))
        self._save()
        self.refresh()

    def _launch(self) -> None:
        if self.state is None:
            return
        staff_id = str(self._campaign_staff.currentData() or "") or None
        door_id = None
        door_box = getattr(self, "_campaign_door", None)
        if self.state.mode == "corporate" and door_box is not None:
            door_id = str(door_box.currentData() or "") or None
        text = launch_campaign(
            self.state,
            str(self._campaign_kind.currentData()),
            str(self._campaign_tone.currentData()),
            str(self._campaign_category.currentData()),
            staff_id,
            door_id,
        )
        self._say(text)
        self._save()
        self.refresh()

    def _book(self) -> None:
        if self.state is None or self._event_host.currentData() is None:
            self._say("Someone has to host.")
            return
        text = schedule_event(
            self.state,
            str(self._event_kind.currentData()),
            str(self._event_host.currentData()),
            self._event_rules.isChecked(),
            str(self._event_category.currentData()),
        )
        self._say(text)
        self._save()
        self.refresh()

    def _cancel_event(self) -> None:
        if self.state is None:
            return
        self._say(cancel_event(self.state))
        self._save()
        self.refresh()

    def _repay(self) -> None:
        if self.state is None:
            return
        self._say(repay_credit(self.state, self._repay_spin.value()))
        self._save()
        self.refresh()

    def _online(self) -> None:
        if self.state is None:
            return
        self._say(open_online(self.state))
        self._save()
        self.refresh()

    def _label(self) -> None:
        if self.state is None:
            return
        self._say(open_label(self.state))
        self._save()
        self.refresh()

    def _open_site(self, offer_id: str) -> None:
        if self.state is None:
            return
        self._say(open_site(self.state, offer_id))
        self._save()
        self.refresh()
