"""The play-mode desktop shell: wallpaper, icons, widgets, taskbar, menus, windows."""

from __future__ import annotations

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QFont, QTextOption
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from open_late.content import HELP
from open_late.ui.chrome import DeskWidget, NotificationCenter, StartMenu, Taskbar, _label
from open_late.ui.desktop import TASKBAR, DesktopIcon, Stage, Toast, WindowManager
from open_late.ui.icons import APPS, app_id_for_index, app_label, icon_pixmap, index_for_app
from open_late.ui.theme import DOWN, TEXT, UP, ui_font


class HelpDialog(QDialog):
    """A readable, scrollable help window — not a tall message box."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("How the desk works")
        self.setModal(True)
        self.resize(640, 520)
        self.setMinimumSize(480, 360)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)
        title = QLabel("How the desk works")
        title.setFont(ui_font(20, QFont.Weight.DemiBold))
        layout.addWidget(title)
        body = QTextEdit()
        body.setReadOnly(True)
        body.setPlainText(HELP.strip())
        body.setStyleSheet(
            f"QTextEdit {{ background: #F7F8FB; color: {TEXT}; border: 1px solid rgba(0,0,0,28); border-radius: 8px; padding: 10px; }}"
        )
        layout.addWidget(body, stretch=1)
        row = QHBoxLayout()
        row.addStretch(1)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        row.addWidget(close)
        layout.addLayout(row)


def fill_help_window(win) -> None:
    """Put the help essay into a mica app window."""
    win.clear_body()
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
    inner = QWidget()
    inner.setObjectName("windowInner")
    inner.setStyleSheet("QWidget#windowInner { background: transparent; }")
    layout = QVBoxLayout(inner)
    layout.setContentsMargins(22, 16, 22, 20)
    layout.setSpacing(10)
    title = QLabel("How the desk works")
    title.setFont(ui_font(20, QFont.Weight.DemiBold))
    layout.addWidget(title)
    body = QLabel(HELP.strip())
    body.setWordWrap(True)
    body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    body.setFont(ui_font(13))
    body.setStyleSheet(f"color: {TEXT}; background: transparent;")
    layout.addWidget(body)
    layout.addStretch(1)
    scroll.setWidget(inner)
    win.body_layout.addWidget(scroll)


class PlayDesktop(Stage):
    """Full play surface hosted as a page in the main stack."""

    open_app = Signal(str)
    open_floor = Signal()
    close_day = Signal()
    next_morning = Signal()
    new_shop = Signal()
    save_now = Signal()
    front_door = Signal()
    help = Signal()
    search_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("app")
        self.wm = WindowManager(self)
        self._corporate = False
        self.icons: list[DesktopIcon] = []
        for index, (app_id, _label, _g, _i) in enumerate(APPS):
            icon = DesktopIcon(app_id, self, corporate=False)
            icon.clicked.connect(lambda _=False, i=app_id: self.open_app.emit(i))
            self.icons.append(icon)

        self.today = DeskWidget("TODAY", self)
        self.people = DeskWidget("ON THE FLOOR", self)
        self.toast = Toast("", "", self, width=300)
        self.toast.hide()

        self.menu = StartMenu(self)
        self.menu.hide()
        self.menu.open_app.connect(self.open_app)
        self.menu.open_floor.connect(self.open_floor)
        self.menu.new_shop.connect(self.new_shop)
        self.menu.save_now.connect(self.save_now)
        self.menu.front_door.connect(self.front_door)
        self.menu.help.connect(self.help)

        self.center = NotificationCenter(self)
        self.center.hide()
        self.center.open_journal.connect(lambda: self.open_app.emit("journal"))

        self.taskbar = Taskbar(self)
        self.taskbar.open_app.connect(self.open_app)
        self.taskbar.open_menu.connect(self.toggle_menu)
        self.taskbar.open_center.connect(self.toggle_center)
        self.taskbar.open_floor.connect(self.open_floor)
        self.taskbar.close_day.connect(self.close_day)
        self.taskbar.next_morning.connect(self.next_morning)
        self.taskbar.search_changed.connect(self._on_search)
        self.taskbar.paint_menu_icon()

        # Aliases the original tests and action wiring still use.
        self.to_desk = self.taskbar.to_desk
        self.close_button = self.taskbar.close_button
        self.next_button = self.taskbar.next_button

        self.status = QLabel(self)
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        self.status.hide()

    # --- chrome layout ---

    def _desk_metrics(self) -> tuple[int, int, int, int]:
        """cols, icon pitch, widget width, widget x."""
        w = self.width()
        cols = 2 if w >= 1100 else 1
        pitch = 80 if w < 1180 else 84
        widget_w = 300 if w >= 1180 else 260
        widget_x = max(16, w - widget_w - 16)
        return cols, pitch, widget_w, widget_x

    def work_area(self) -> QRect:
        w, h = self.width(), self.height()
        cols, pitch, widget_w, _x = self._desk_metrics()
        left = 16 + pitch * cols
        right = 16 + widget_w + 8
        return QRect(left, 8, max(480, w - left - right), max(300, h - TASKBAR - 16))

    def widget_x(self) -> int:
        return self._desk_metrics()[3]

    def layout_chrome(self) -> None:
        w, h = max(self.width(), 1), max(self.height(), 1)
        self.taskbar.setGeometry(0, h - TASKBAR, w, TASKBAR)
        self.taskbar.raise_()
        # Two columns from the 1100 minimum so every app stays on the desk.
        cols, pitch, _ww, _wx = self._desk_metrics()
        for index, icon in enumerate(self.icons):
            icon.setVisible(True)
            col, row = index % cols, index // cols
            icon.move(8 + col * pitch, 8 + row * 76)
        # Widgets sit on the right at 1366; tuck under the tray at 1100 if needed.
        show_widgets = w >= 1100
        self.today.setVisible(show_widgets)
        self.people.setVisible(show_widgets)
        if show_widgets:
            x = self.widget_x()
            self.today.setFixedWidth(300 if w >= 1180 else 260)
            self.people.setFixedWidth(self.today.width())
            # Size to content so Today / On the floor never collapse to a title bar.
            for panel, floor in ((self.today, 200), (self.people, 140)):
                panel.setMinimumHeight(floor)
                panel.adjustSize()
                height = max(panel.sizeHint().height(), floor)
                panel.setFixedHeight(height)
            th = self.today.height()
            ph = self.people.height()
            gap = 12
            if 12 + th + gap + ph > h - TASKBAR - 12:
                available = max(280, h - TASKBAR - 24)
                th = min(th, max(180, (available - gap) // 2))
                ph = min(ph, max(120, available - gap - th))
                self.today.setFixedHeight(th)
                self.people.setFixedHeight(ph)
            self.today.move(x, 12)
            self.people.move(x, 12 + th + gap)
        if self.menu.isVisible():
            self._place_menu()
        if self.center.isVisible():
            self._place_center()
        if self.toast.isVisible():
            self._place_toast()
        self.lift_chrome()

    def lift_chrome(self) -> None:
        if self.toast.isVisible():
            self.toast.raise_()
        if self.menu.isVisible():
            self.menu.raise_()
        if self.center.isVisible():
            self.center.raise_()
        self.taskbar.raise_()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.layout_chrome()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.layout_chrome()

    def _place_menu(self) -> None:
        # Sit in the free desk between the icons and the widgets, above the taskbar.
        cols, pitch, _ww, widget_left = self._desk_metrics()
        icons_right = 16 + pitch * cols
        if not self.today.isVisible():
            widget_left = self.width() - 8
        available = max(420, widget_left - icons_right - 16)
        width = min(580, available)
        height = min(600, max(420, self.height() - TASKBAR - 20))
        self.menu.setFixedSize(width, height)
        gap = widget_left - icons_right
        x = icons_right + max(8, (gap - width) // 2)
        x = min(x, max(8, widget_left - width - 8))
        y = max(8, self.height() - TASKBAR - height - 10)
        self.menu.move(x, y)

    def _place_center(self) -> None:
        height = min(self.height() - TASKBAR - 16, 620)
        self.center.setFixedHeight(max(360, height))
        self.center.move(self.width() - self.center.width() - 12, 8)

    def _place_toast(self) -> None:
        self.toast.adjustSize()
        x = min(self.widget_x(), self.width() - self.toast.width() - 12)
        y = self.height() - TASKBAR - self.toast.height() - 12
        # Prefer sitting under the staff widget when there is room.
        if self.people.isVisible():
            candidate = self.people.geometry().bottom() + 12
            if candidate + self.toast.height() < self.height() - TASKBAR - 8:
                y = candidate
                x = self.people.x()
                self.toast.setFixedWidth(self.people.width())
        self.toast.move(x, y)

    def toggle_menu(self) -> None:
        if self.menu.isVisible():
            self.menu.hide()
        else:
            self.center.hide()
            self._place_menu()
            self.menu.show()
        self.lift_chrome()

    def toggle_center(self) -> None:
        if self.center.isVisible():
            self.center.hide()
        else:
            self.menu.hide()
            self._place_center()
            self.center.show()
        self.lift_chrome()

    def hide_overlays(self) -> None:
        self.menu.hide()
        self.center.hide()

    def show_toast(self, title: str, body: str) -> Toast:
        # Rebuild the toast so actions from the last note do not linger.
        if self.toast is not None:
            self.toast.hide()
            self.toast.setParent(None)
            self.toast.deleteLater()
        self.toast = Toast(title, body, self, width=300)
        self._place_toast()
        self.toast.show()
        self.lift_chrome()
        return self.toast

    def hide_toast(self) -> None:
        self.toast.hide()

    def _on_search(self, text: str) -> None:
        if text.strip() and not self.menu.isVisible():
            self._place_menu()
            self.menu.show()
            self.lift_chrome()
        self.menu.search.setText(text)
        self.search_changed.emit(text)

    def default_geometry(self, app_id: str) -> QRect:
        area = self.work_area()
        # Use almost all of the free desk so sheets fit at 1366 without scrolling.
        # A small cascade offset still leaves title bars visible.
        order = (
            "overview", "sales", "inventory", "orders", "staff", "customers",
            "marketing", "books", "expansion", "market", "journal", "settings", "help",
        )
        index = order.index(app_id) if app_id in order else 4
        # Almost the full desk, with a little cascade room so title bars stay visible.
        width = max(480, area.width() - 40)
        height = max(300, area.height() - 28)
        if app_id in ("journal", "settings", "help", "market"):
            width = min(width, max(560, int(area.width() * 0.90)))
            height = min(height, max(480, int(area.height() * 0.92)))
        # Overview, inventory and stores use every leftover pixel of height.
        if app_id in ("overview", "inventory", "expansion"):
            width = max(width, area.width() - 24)
            height = area.height() - 12
        dx = (index % 6) * 18
        dy = (index % 6) * 14
        x = area.x() + min(dx, max(0, area.width() - width))
        y = area.y() + min(dy, max(0, area.height() - height))
        x = min(max(area.x(), x), max(area.x(), area.right() - width))
        y = min(max(area.y(), y), max(area.y(), area.bottom() - height))
        return QRect(x, y, width, height)

    def set_corporate(self, corporate: bool) -> None:
        if corporate == self._corporate and self.icons:
            return
        self._corporate = corporate
        for icon in self.icons:
            # Recreate the caption so Stores replaces Expansion.
            icon.setParent(None)
        self.icons = []
        for app_id, _label, _g, _i in APPS:
            icon = DesktopIcon(app_id, self, corporate=corporate)
            icon.clicked.connect(lambda _=False, i=app_id: self.open_app.emit(i))
            self.icons.append(icon)
        self.layout_chrome()
