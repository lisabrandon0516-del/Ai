"""Taskbar, Start menu, notification center, and desktop widgets for Concept G."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from open_late.ui.desktop import GlassPanel, paint_mica
from open_late.ui.icons import APPS, app_label, icon_pixmap, start_mark
from open_late.ui.theme import ACCENT, ACCENT_TEXT, DOWN, TEXT, ui_font


def _label(text: str, size: int = 13, weight=QFont.Weight.Normal, color: str = TEXT, wrap: bool = False) -> QLabel:
    lab = QLabel(text)
    lab.setFont(ui_font(size, weight))
    lab.setStyleSheet(f"color: {color}; background: transparent;")
    lab.setWordWrap(wrap)
    return lab


class IconButton(QPushButton):
    def __init__(self, app_id: str, size: int = 26, parent=None, marked: bool = False):
        super().__init__(parent)
        self.app_id = app_id
        self._size = size
        self._pix = icon_pixmap(app_id, size)
        self._marked = marked
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFixedSize(size + 12, size + 12)
        self.setToolTip(app_label(app_id))
        self.setStyleSheet("QPushButton { background: transparent; border: none; }")

    def setMarked(self, marked: bool) -> None:
        self._marked = marked
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._marked:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(11, 108, 189, 40))
            painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 8, 8)
        x = (self.width() - self._size) // 2
        y = (self.height() - self._size) // 2
        painter.drawPixmap(x, y, self._pix)
        painter.end()


class Taskbar(GlassPanel):
    open_app = Signal(str)
    open_menu = Signal()
    open_center = Signal()
    open_floor = Signal()
    close_day = Signal()
    next_morning = Signal()
    search_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent, radius=0)
        self.setFixedHeight(52)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 6, 10, 6)
        row.setSpacing(8)

        self.menu_btn = QPushButton()
        self.menu_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.menu_btn.setFixedSize(40, 40)
        self.menu_btn.setToolTip("Menu")
        self.menu_btn.setStyleSheet("QPushButton { background: transparent; border: none; border-radius: 8px; } QPushButton:hover { background: rgba(255,255,255,50); }")
        self._menu_icon = start_mark(28)
        self.menu_btn.clicked.connect(self.open_menu.emit)
        row.addWidget(self.menu_btn)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search the shop")
        self.search.setFixedHeight(34)
        self.search.setMinimumWidth(120)
        self.search.setMaximumWidth(220)
        self.search.setFont(ui_font(12))
        self.search.textChanged.connect(self.search_changed.emit)
        self.search.returnPressed.connect(self.open_menu.emit)
        row.addWidget(self.search)

        self.pin_wrap = QWidget()
        self.pin_wrap.setObjectName("pinWrap")
        self.pin_wrap.setStyleSheet("QWidget#pinWrap { background: transparent; }")
        self.pin_row = QHBoxLayout(self.pin_wrap)
        self.pin_row.setContentsMargins(0, 0, 0, 0)
        self.pin_row.setSpacing(2)
        self.pins: list[IconButton] = []
        for app_id in ("overview", "sales", "inventory", "orders", "staff", "books", "journal"):
            btn = IconButton(app_id, 26)
            btn.clicked.connect(lambda _=False, i=app_id: self.open_app.emit(i))
            self.pin_row.addWidget(btn)
            self.pins.append(btn)
        row.addWidget(self.pin_wrap, stretch=1)

        # Phase action — one of these is visible at a time.
        self.to_desk = QPushButton("Open the floor")
        self.to_desk.setObjectName("toDesk")
        self.to_desk.setMinimumHeight(32)
        self.to_desk.setMinimumWidth(130)
        self.to_desk.clicked.connect(self.open_floor.emit)
        self.close_button = QPushButton("Close the day")
        self.close_button.setObjectName("closeDay")
        self.close_button.setMinimumHeight(32)
        self.close_button.clicked.connect(self.close_day.emit)
        self.next_button = QPushButton("Next morning")
        self.next_button.setObjectName("nextMorning")
        self.next_button.setMinimumHeight(32)
        self.next_button.clicked.connect(self.next_morning.emit)
        for button in (self.to_desk, self.close_button, self.next_button):
            button.hide()
            row.addWidget(button)

        self.cash = _label("$0", 12, QFont.Weight.DemiBold)
        self.cash.setMinimumWidth(64)
        self.cash.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(self.cash)

        self.urgent = QPushButton("0")
        self.urgent.setFixedSize(22, 22)
        self.urgent.setFont(ui_font(11, QFont.Weight.Bold))
        self.urgent.setCursor(Qt.CursorShape.PointingHandCursor)
        self.urgent.setToolTip("Notifications")
        self.urgent.clicked.connect(self.open_center.emit)
        row.addWidget(self.urgent)

        time_col = QVBoxLayout()
        time_col.setSpacing(0)
        time_col.setContentsMargins(0, 0, 0, 0)
        self.clock = _label("11:00", 12, QFont.Weight.DemiBold)
        self.clock.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.day = _label("Sun  ·  Day 1", 10, color="#5C5C5C")
        self.day.setAlignment(Qt.AlignmentFlag.AlignRight)
        time_col.addWidget(self.clock)
        time_col.addWidget(self.day)
        row.addLayout(time_col)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        paint_mica(painter, self, 0)
        painter.end()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        narrow = self.width() < 1200
        self.search.setFixedWidth(140 if narrow else 200)
        # Hide later pins when the bar is tight so labels never clip.
        visible = 4 if self.width() < 1120 else (5 if narrow else 7)
        for index, pin in enumerate(self.pins):
            pin.setVisible(index < visible)

    def set_tray(self, cash: str, urgent: int, clock: str, day: str) -> None:
        self.cash.setText(cash)
        self.urgent.setText(str(urgent))
        self.urgent.setToolTip(f"{urgent} urgent note" if urgent else "Notifications")
        if urgent:
            self.urgent.setStyleSheet(
                f"QPushButton {{ color: #FFFFFF; background: {DOWN}; border: none; border-radius: 11px; }}"
            )
        else:
            self.urgent.setStyleSheet(
                "QPushButton { color: #1A1A1A; background: rgba(0,0,0,16); border: none; border-radius: 11px; }"
            )
        self.clock.setText(clock)
        self.day.setText(day)

    def set_phase(self, phase: str, failed: bool = False, urgent: int = 0) -> None:
        self.to_desk.setVisible(phase == "morning")
        self.close_button.setVisible(phase == "desk")
        self.next_button.setVisible(phase in ("evening", "gameover"))
        if phase == "morning":
            self.to_desk.setText("Open the floor" if urgent == 0 else f"Open the floor ({urgent})")
        self.next_button.setText("Back to the front" if failed else "Next morning")

    def set_marked(self, app_id: str | None) -> None:
        for pin in self.pins:
            pin.setMarked(pin.app_id == app_id)

    def paint_menu_icon(self) -> None:
        def paint(event, btn=self.menu_btn, pix=self._menu_icon):
            painter = QPainter(btn)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            if btn.underMouse():
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(255, 255, 255, 50))
                painter.drawRoundedRect(btn.rect().adjusted(2, 2, -2, -2), 8, 8)
            painter.drawPixmap((btn.width() - pix.width()) // 2, (btn.height() - pix.height()) // 2, pix)
            painter.end()

        self.menu_btn.paintEvent = paint
        self.menu_btn.update()


class StartMenu(GlassPanel):
    open_app = Signal(str)
    open_floor = Signal()
    new_shop = Signal()
    save_now = Signal()
    front_door = Signal()
    help = Signal()

    def __init__(self, parent=None):
        super().__init__(parent, radius=16)
        self.setFixedSize(580, 600)
        self._corporate = False
        self._filter = ""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 16)
        layout.setSpacing(10)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search the shop")
        self.search.setFixedHeight(36)
        self.search.setFont(ui_font(13))
        layout.addWidget(self.search)
        self.cta = QPushButton("Open the floor")
        self.cta.setMinimumHeight(36)
        self.cta.clicked.connect(self.open_floor.emit)
        layout.addWidget(self.cta)
        layout.addWidget(_label("PINNED", 10, QFont.Weight.DemiBold, "#7A7A7A"))
        self.grid_host = QWidget()
        self.grid_host.setObjectName("gridHost")
        self.grid_host.setStyleSheet("QWidget#gridHost { background: transparent; }")
        self.grid = QGridLayout(self.grid_host)
        self.grid.setSpacing(8)
        self.grid.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.grid_host)
        layout.addWidget(_label("RECOMMENDED", 10, QFont.Weight.DemiBold, "#7A7A7A"))
        self.rec_host = QVBoxLayout()
        self.rec_host.setSpacing(4)
        layout.addLayout(self.rec_host)
        layout.addStretch(1)
        foot = QHBoxLayout()
        mark = QLabel()
        mark.setPixmap(start_mark(28))
        mark.setStyleSheet("background: transparent;")
        col = QVBoxLayout()
        col.setSpacing(0)
        self.owner = _label("Owner", 12, QFont.Weight.DemiBold)
        self.shop = _label("Retail Rivals", 11, color="#5C5C5C")
        col.addWidget(self.owner)
        col.addWidget(self.shop)
        foot.addWidget(mark)
        foot.addLayout(col)
        foot.addStretch(1)
        for text, signal in (("New shop", self.new_shop), ("Save", self.save_now), ("Front", self.front_door), ("Help", self.help)):
            btn = QPushButton(text)
            btn.setObjectName("quiet")
            btn.setMinimumHeight(30)
            btn.clicked.connect(signal.emit)
            foot.addWidget(btn)
        layout.addLayout(foot)
        self._rebuild_grid()
        self.search.textChanged.connect(self._on_filter)

    def set_shop(self, name: str, corporate: bool, phase: str, urgent: int) -> None:
        self.shop.setText(name)
        self._corporate = corporate
        self.cta.setVisible(phase == "morning")
        self.cta.setText("Open the floor" if urgent == 0 else f"Open the floor ({urgent} urgent)")
        self._rebuild_grid()

    def set_recommended(self, rows: list[tuple[str, str, str]]) -> None:
        while self.rec_host.count():
            item = self.rec_host.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        for title, detail, app_id in rows[:3]:
            row = QPushButton()
            row.setCursor(Qt.CursorShape.PointingHandCursor)
            row.setStyleSheet(
                "QPushButton { background: transparent; border: none; border-radius: 8px; text-align: left; }"
                "QPushButton:hover { background: rgba(0,0,0,10); }"
            )
            row.setFixedHeight(44)
            box = QHBoxLayout(row)
            box.setContentsMargins(8, 4, 8, 4)
            ic = QLabel()
            ic.setPixmap(icon_pixmap(app_id, 28))
            ic.setStyleSheet("background: transparent;")
            col = QVBoxLayout()
            col.setSpacing(0)
            col.addWidget(_label(title, 12, QFont.Weight.DemiBold))
            col.addWidget(_label(detail, 11, color="#5C5C5C"))
            box.addWidget(ic)
            box.addLayout(col, stretch=1)
            row.clicked.connect(lambda _=False, i=app_id: self.open_app.emit(i))
            self.rec_host.addWidget(row)

    def _on_filter(self, text: str) -> None:
        self._filter = text.strip().lower()
        self._rebuild_grid()

    def _rebuild_grid(self) -> None:
        while self.grid.count():
            item = self.grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        shown = 0
        for app_id, label, _g, _i in APPS:
            name = app_label(app_id, corporate=self._corporate)
            if self._filter and self._filter not in name.lower() and self._filter not in app_id:
                continue
            cell = QPushButton()
            cell.setCursor(Qt.CursorShape.PointingHandCursor)
            cell.setFixedSize(124, 72)
            cell.setStyleSheet(
                "QPushButton { background: rgba(255,255,255,140); border: 1px solid rgba(0,0,0,20); border-radius: 10px; }"
                "QPushButton:hover { background: rgba(255,255,255,200); }"
            )
            inner = QVBoxLayout(cell)
            inner.setContentsMargins(6, 8, 6, 8)
            inner.setSpacing(4)
            ic = QLabel()
            ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
            ic.setPixmap(icon_pixmap(app_id, 28))
            ic.setStyleSheet("background: transparent;")
            name_lab = _label(name, 11, QFont.Weight.Medium)
            name_lab.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            inner.addWidget(ic)
            inner.addWidget(name_lab)
            cell.clicked.connect(lambda _=False, i=app_id: self.open_app.emit(i))
            self.grid.addWidget(cell, shown // 4, shown % 4)
            shown += 1


class NotificationCenter(GlassPanel):
    open_journal = Signal()

    def __init__(self, parent=None):
        super().__init__(parent, radius=16)
        self.setFixedWidth(340)
        self.box = QVBoxLayout(self)
        self.box.setContentsMargins(16, 16, 16, 16)
        self.box.setSpacing(10)
        self.clock = _label("11:00", 36, QFont.Weight.Bold)
        self.meta = _label("Sunday  ·  Day 7  ·  Morning", 13, color="#5C5C5C")
        self.box.addWidget(self.clock)
        self.box.addWidget(self.meta)
        self.stats = QHBoxLayout()
        self.box.addLayout(self.stats)
        self.box.addWidget(_label("NOTIFICATIONS", 10, QFont.Weight.DemiBold, "#7A7A7A"))
        self.feed = QVBoxLayout()
        self.feed.setSpacing(8)
        self.box.addLayout(self.feed)
        self.box.addStretch(1)
        more = QPushButton("Open the journal")
        more.setObjectName("quiet")
        more.clicked.connect(self.open_journal.emit)
        self.box.addWidget(more)

    def set_header(self, clock: str, meta: str, cash: str, urgent: int, reviews: str) -> None:
        self.clock.setText(clock)
        self.meta.setText(meta)
        while self.stats.count():
            item = self.stats.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        for caption, value in (("Drawer", cash), ("Urgent", str(urgent)), ("Reviews", reviews)):
            cell = QVBoxLayout()
            cell.setSpacing(0)
            cell.addWidget(_label(caption, 10, QFont.Weight.DemiBold, "#7A7A7A"))
            cell.addWidget(_label(value, 14, QFont.Weight.DemiBold))
            wrap = QWidget()
            wrap.setObjectName("statWrap")
            wrap.setStyleSheet("QWidget#statWrap { background: transparent; }")
            wrap.setLayout(cell)
            self.stats.addWidget(wrap)

    def set_notes(self, notes: list[tuple[bool, str, str, list[tuple[str, object]]]]) -> None:
        while self.feed.count():
            item = self.feed.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        if not notes:
            self.feed.addWidget(_label("The desk is clear.", 13, color="#5C5C5C"))
            return
        for urgent, title, body, actions in notes[:5]:
            card = QFrame()
            card.setObjectName("noteCard")
            card.setStyleSheet(
                "QFrame#noteCard { background: rgba(255,255,255,90); border: 1px solid rgba(0,0,0,28); border-radius: 12px; }"
                "QFrame#noteCard QLabel { background: transparent; border: none; }"
            )
            box = QVBoxLayout(card)
            box.setContentsMargins(12, 10, 12, 10)
            box.setSpacing(4)
            box.addWidget(_label("Urgent" if urgent else "Note", 10, QFont.Weight.DemiBold, DOWN if urgent else "#7A7A7A"))
            box.addWidget(_label(title, 13, QFont.Weight.DemiBold, wrap=True))
            snippet = body.split(".")[0].strip()
            if snippet and not snippet.endswith("."):
                snippet += "."
            text = _label(snippet, 11, color="#5C5C5C", wrap=True)
            box.addWidget(text)
            if actions:
                row = QHBoxLayout()
                for index, (label, slot) in enumerate(actions[:2]):
                    btn = QPushButton(label)
                    if index != 0:
                        btn.setObjectName("quiet")
                    btn.setMinimumHeight(28)
                    btn.clicked.connect(slot)
                    row.addWidget(btn)
                row.addStretch(1)
                box.addLayout(row)
            self.feed.addWidget(card)


class DeskWidget(GlassPanel):
    def __init__(self, title: str, parent=None):
        super().__init__(parent, radius=10)
        self.setFixedWidth(300)
        self.box = QVBoxLayout(self)
        self.box.setContentsMargins(14, 12, 14, 14)
        self.box.setSpacing(6)
        self.box.addWidget(_label(title, 11, QFont.Weight.DemiBold, "#7A7A7A"))


def clear_layout(layout) -> None:
    while layout.count() > 1:
        item = layout.takeAt(1)
        widget = item.widget()
        if widget is not None:
            widget.hide()
            widget.setParent(None)
            widget.deleteLater()
        elif item.layout() is not None:
            nested = item.layout()
            while nested.count():
                child = nested.takeAt(0)
                w = child.widget()
                if w is not None:
                    w.hide()
                    w.setParent(None)
                    w.deleteLater()
