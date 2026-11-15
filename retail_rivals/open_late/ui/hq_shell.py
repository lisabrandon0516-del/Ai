"""Corporate HQ play shell: navy rail, top bar, store switcher, alerts, one pane."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QImage, QPalette, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from open_late.content import HELP
from open_late.text import money, weekday_name
from open_late.ui.hq_adapter import chain_info, chain_logo_path, regions_for, store_ids, store_pos
from open_late.ui.hq_economy import EconomyPage
from open_late.ui.hq_pages import DashboardPage, PosPage, StoresPage
from open_late.ui.hq_planogram import PlanogramPage
from open_late.ui.icons import icon_pixmap, quiet_icon
from open_late.ui.theme import ACCENT, DASH_BG, DASH_MUTED, DASH_TEXT, DOWN, HQ_CANVAS, HQ_MUTED, HQ_TITLE, RAIL, RR_YELLOW, TEXT, dash_chrome_stylesheet, hq_stylesheet, ui_font


# app_id, label, icon id (from icons.TILE), desk index or None
RAIL_ITEMS = [
    ("home", "Dashboard", "overview", None),
    ("stores", "Store Portfolio", "expansion", None),
    ("sales", "Sales", "sales", 1),
    ("inventory", "Inventory", "inventory", 2),
    ("orders", "Orders", "orders", 3),
    ("staff", "Staff", "staff", 4),
    ("customers", "Customers", "customers", 5),
    ("marketing", "Marketing", "marketing", 6),
    ("books", "Finance", "books", 7),
    ("economy", "Economy", "economy", None),
    ("planograms", "Planograms", "expansion", None),
    ("market", "Market", "market", 9),
    ("journal", "Inbox", "journal", 10),
    ("settings", "Hours", "settings", 11),
    ("pos", "POS", "settings", None),
]

LEGACY_IDS = {item[0] for item in RAIL_ITEMS if item[3] is not None} | {"planograms", "expansion", "overview"}


def rail_label(app_id: str, corporate: bool) -> str:
    if app_id == "planograms":
        return "Planograms" if corporate else "Expansion"
    for ident, label, _icon, _index in RAIL_ITEMS:
        if ident == app_id:
            return label
    return app_id.title()



BRAND_LOGO = Path(__file__).resolve().parent.parent / "assets" / "brand" / "retail_rivals_logo.png"


def brand_logo_pixmap(max_w: int, max_h: int) -> QPixmap:
    if not BRAND_LOGO.exists():
        return QPixmap()
    pix = QPixmap(str(BRAND_LOGO))
    if pix.isNull():
        return pix
    # The official wordmark is a large RGBA canvas with padding; crop to the
    # opaque ink so the rail mark is not a tiny tile in empty space.
    image = pix.toImage()
    rect = image.alphaRegion().boundingRect() if hasattr(image, "alphaRegion") else None
    if rect is None or not rect.isValid():
        min_x, min_y, max_x, max_y = image.width(), image.height(), -1, -1
        for y in range(0, image.height(), 2):
            for x in range(0, image.width(), 2):
                if image.pixelColor(x, y).alpha() > 20:
                    if x < min_x:
                        min_x = x
                    if y < min_y:
                        min_y = y
                    if x > max_x:
                        max_x = x
                    if y > max_y:
                        max_y = y
        if max_x >= min_x:
            from PySide6.QtCore import QRect
            # step-2 scan; pad a couple of pixels back out
            rect = QRect(max(0, min_x - 2), max(0, min_y - 2), max_x - min_x + 5, max_y - min_y + 5)
            rect = rect.intersected(image.rect())
        else:
            from PySide6.QtCore import QRect
            rect = image.rect()
    else:
        from PySide6.QtCore import QRect
        rect = QRect(rect)
    if rect.width() > 8 and rect.height() > 8:
        pix = QPixmap.fromImage(image.copy(rect))
    return pix.scaled(
        max_w,
        max_h,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


def _lab(text: str, size: int = 13, weight=QFont.Weight.Normal, color: str = TEXT) -> QLabel:
    label = QLabel(text)
    label.setFont(ui_font(size, weight))
    label.setStyleSheet(f"color: {color}; background: transparent;")
    return label


class Rail(QFrame):
    open_app = Signal(str)
    new_shop = Signal()
    save_now = Signal()
    front_door = Signal()
    help = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("hqRail")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAutoFillBackground(True)
        pal = self.palette()
        pal.setColor(QPalette.ColorRole.Window, QColor(RAIL))
        pal.setColor(QPalette.ColorRole.Base, QColor(RAIL))
        self.setPalette(pal)
        self.setFixedWidth(220)
        self._corporate = False
        self._compact = False
        self.buttons: dict[str, QPushButton] = {}
        self.quiet_buttons: dict[str, QPushButton] = {}
        self.scroll = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(2)
        self.logo = QLabel()
        self.logo.setObjectName("railLogo")
        self.logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.logo.setToolTip("Retail Rivals")
        self.logo.setMinimumHeight(56)
        self.logo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._apply_logo()
        layout.addWidget(self.logo)
        self.nav_host = QWidget()
        self.nav_host.setObjectName("railNavHost")
        self.nav_host.setStyleSheet("background: transparent;")
        self.nav = QVBoxLayout(self.nav_host)
        self.nav.setContentsMargins(0, 2, 0, 0)
        self.nav.setSpacing(1)
        for app_id, label, icon_id, _index in RAIL_ITEMS:
            btn = QPushButton(f"  {label}")
            btn.setObjectName("railNav")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            pix = icon_pixmap(icon_id, 16)
            btn.setIcon(QIcon(pix))
            btn.setIconSize(pix.size())
            btn.setMinimumHeight(26)
            btn.setMaximumHeight(28)
            btn.setToolTip(label)
            btn.clicked.connect(lambda _=False, ident=app_id: self.open_app.emit(ident))
            self.nav.addWidget(btn)
            self.buttons[app_id] = btn
        self.nav.addStretch(1)
        # No scroll area: every entry must stay on-screen at 1366x768 and 1100x700.
        layout.addWidget(self.nav_host, stretch=1)
        self.footer = QWidget()
        self.footer.setObjectName("railFooter")
        self.footer_box = QHBoxLayout(self.footer)
        self.footer_box.setContentsMargins(0, 4, 0, 0)
        self.footer_box.setSpacing(4)
        for text, signal, kind in (
            ("Help", self.help, "help"),
            ("Save", self.save_now, "save"),
            ("Front door", self.front_door, "door"),
        ):
            btn = QPushButton(text)
            btn.setObjectName("railQuiet")
            btn.setToolTip(text)
            btn.setMinimumHeight(26)
            btn.setMaximumHeight(28)
            glyph = quiet_icon(kind, 14)
            btn.setIcon(QIcon(glyph))
            btn.setIconSize(glyph.size())
            btn.clicked.connect(signal.emit)
            self.footer_box.addWidget(btn, stretch=1)
            self.quiet_buttons[text] = btn
        layout.addWidget(self.footer)
        self.inbox_badge = 0

    def _apply_logo(self) -> None:
        if self._compact:
            # The wordmark is too wide for a 64px rail; use the square mark instead.
            mark = BRAND_LOGO.parent / "mark.png"
            self.logo.setMinimumHeight(36)
            pix = QPixmap()
            if mark.exists():
                raw = QPixmap(str(mark))
                if not raw.isNull():
                    pix = raw.scaled(
                        36,
                        36,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
            if pix.isNull():
                pix = brand_logo_pixmap(36, 36)
        else:
            self.logo.setMinimumHeight(56)
            pix = brand_logo_pixmap(200, 52)
        if not pix.isNull():
            self.logo.setPixmap(pix)
            self.logo.setFixedHeight(max(self.logo.minimumHeight(), pix.height() + 4))
            self.logo.setText("")
        else:
            self.logo.setPixmap(QPixmap())
            self.logo.setText("Retail Rivals")
            self.logo.setStyleSheet("color: #E8EEF5; background: transparent; font-weight: 700;")

    def set_compact(self, compact: bool) -> None:
        changed = compact != self._compact
        self._compact = compact
        if changed:
            for app_id, btn in self.buttons.items():
                label = rail_label(app_id, self._corporate)
                btn.setText("" if compact else f"  {label}")
            self._layout_footer()
        self.setFixedWidth(64 if self._compact else 220)
        self._apply_logo()

    def _layout_footer(self) -> None:
        """Wide: one labeled row. Compact: a stacked icon column so 64px stays readable."""
        while self.footer_box.count():
            item = self.footer_box.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
        # Swap the layout type when width mode changes.
        old = self.footer.layout()
        if old is not None:
            QWidget().setLayout(old)
        if self._compact:
            box = QVBoxLayout(self.footer)
            box.setContentsMargins(0, 4, 0, 0)
            box.setSpacing(2)
        else:
            box = QHBoxLayout(self.footer)
            box.setContentsMargins(0, 4, 0, 0)
            box.setSpacing(4)
        self.footer_box = box
        for text, btn in self.quiet_buttons.items():
            btn.setText("" if self._compact else text)
            btn.setParent(self.footer)
            box.addWidget(btn, stretch=1)

    def set_corporate(self, corporate: bool) -> None:
        self._corporate = corporate
        if "planograms" in self.buttons:
            label = rail_label("planograms", corporate)
            if not self._compact:
                self.buttons["planograms"].setText(f"  {label}")
            self.buttons["planograms"].setToolTip(label)

    def set_active(self, app_id: str) -> None:
        for ident, btn in self.buttons.items():
            btn.setObjectName("railNavOn" if ident == app_id else "railNav")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def set_inbox(self, count: int, urgent: int) -> None:
        self.inbox_badge = count
        btn = self.buttons.get("journal")
        if btn is None:
            return
        label = rail_label("journal", self._corporate)
        if count and not self._compact:
            btn.setText(f"  {label}  ({count})")
        elif not self._compact:
            btn.setText(f"  {label}")
        btn.setToolTip(f"{count} open notes" if count else label)
        if urgent:
            btn.setStyleSheet("QPushButton#railNav, QPushButton#railNavOn { color: #FFB4AC; }")
        else:
            btn.setStyleSheet("")


class TopBar(QFrame):
    open_alerts = Signal()
    scope_changed = Signal(str, object)
    open_floor = Signal()
    close_day = Signal()
    next_morning = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("hqTopBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(48)
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 6, 12, 6)
        row.setSpacing(8)
        self.switcher = QPushButton("All stores")
        self.switcher.setObjectName("scopeBtn")
        self.switcher.setMinimumWidth(140)
        self.switcher.setMinimumHeight(30)
        self.switcher.setCursor(Qt.CursorShape.PointingHandCursor)
        self.menu = QMenu(self.switcher)
        self.switcher.setMenu(self.menu)
        self.switcher.clicked.connect(self.switcher.showMenu)
        self.chain_chip = QFrame()
        self.chain_chip.setObjectName("chainChip")
        chip = QHBoxLayout(self.chain_chip)
        chip.setContentsMargins(6, 2, 10, 2)
        chip.setSpacing(6)
        self.chain_logo = QLabel()
        self.chain_logo.setObjectName("chainLogo")
        self.chain_logo.setFixedSize(36, 24)
        self.chain_logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.chain_name = _lab("MegaMart", 12, QFont.Weight.DemiBold)
        self.chain_name.setObjectName("chainName")
        chip.addWidget(self.chain_logo)
        chip.addWidget(self.chain_name)
        row.addWidget(self.chain_chip)
        row.addWidget(self.switcher)
        self.search = QLineEdit()
        self.search.setObjectName("topSearch")
        self.search.setPlaceholderText("Search stores, cities, or states…")
        self.search.setMinimumWidth(200)
        self.search.setMaximumWidth(280)
        row.addWidget(self.search)
        self.breadcrumb = _lab("Dashboard  /  All stores", 12, color=HQ_MUTED)
        self.breadcrumb.setObjectName("breadcrumb")
        row.addWidget(self.breadcrumb, stretch=1)
        self.alerts = QPushButton("0")
        self.alerts.setObjectName("alertsBtn")
        self.alerts.setFixedSize(28, 28)
        self.alerts.setCursor(Qt.CursorShape.PointingHandCursor)
        self.alerts.setToolTip("Notifications")
        self.alerts.clicked.connect(self.open_alerts.emit)
        row.addWidget(self.alerts)
        self.cash = _lab("$0", 12, QFont.Weight.DemiBold)
        self.cash.setObjectName("trayCash")
        row.addWidget(self.cash)
        self.day = _lab("Mon  ·  Day 1  ·  Morning", 11, color=HQ_MUTED)
        self.day.setObjectName("dayChip")
        self.day.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self.day)
        self.to_desk = QPushButton("Open the day")
        self.to_desk.setObjectName("toDesk")
        self.to_desk.setMinimumHeight(30)
        self.to_desk.clicked.connect(self.open_floor.emit)
        self.close_button = QPushButton("Close the day")
        self.close_button.setObjectName("closeDay")
        self.close_button.setMinimumHeight(30)
        self.close_button.clicked.connect(self.close_day.emit)
        self.next_button = QPushButton("Next morning")
        self.next_button.setObjectName("nextMorning")
        self.next_button.setMinimumHeight(30)
        self.next_button.clicked.connect(self.next_morning.emit)
        for button in (self.to_desk, self.close_button, self.next_button):
            button.hide()
            row.addWidget(button)
        self._scope = ("all", None)

    def set_scope_menu(self, state) -> None:
        self.menu.clear()
        action = self.menu.addAction("All stores")
        action.triggered.connect(lambda: self.scope_changed.emit("all", None))
        if state is None or not state.doors:
            if state is not None:
                action = self.menu.addAction(state.shop_name)
                action.triggered.connect(lambda: self.scope_changed.emit("store", "evansville"))
            return
        for region in regions_for(state):
            self.menu.addSeparator()
            region_action = self.menu.addAction(region)
            region_action.triggered.connect(lambda _=False, name=region: self.scope_changed.emit("region", name))
            for door in state.doors:
                if door.region != region:
                    continue
                pip = "●" if door.status == "open" else "○"
                store_action = self.menu.addAction(f"    {pip}  {door.city}, {door.state_name}")
                store_action.triggered.connect(lambda _=False, ident=door.id: self.scope_changed.emit("store", ident))

    def set_scope_label(self, kind: str, scope_id: str | None, state) -> None:
        self._scope = (kind, scope_id)
        if kind == "region" and scope_id:
            text = scope_id
        elif kind == "store" and scope_id:
            door = next((item for item in (state.doors if state else []) if item.id == scope_id), None)
            text = f"{door.city}, {door.state_name}" if door else (state.shop_name if state else "Store")
        else:
            text = "All stores"
        self.switcher.setText(text)

    def set_chain(self, info: dict) -> None:
        name = str(info.get("name") or "MegaMart")
        self.chain_name.setText(name)
        self.chain_chip.setToolTip(name)
        path = chain_logo_path(info)
        pix = QPixmap(str(path)) if path.exists() else QPixmap()
        if not pix.isNull():
            self.chain_logo.setPixmap(pix.scaled(36, 24, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        else:
            self.chain_logo.setText(name[:1])

    def set_breadcrumb(self, module: str, scope: str) -> None:
        self.breadcrumb.setText(f"{module}  /  {scope}")

    def set_tray(self, cash: str, urgent: int, day: str, cash_tip: str | None = None) -> None:
        self.cash.setText(cash)
        self.cash.setToolTip(cash_tip or cash)
        self.alerts.setText(str(urgent))
        self.day.setText(day)
        if urgent:
            self.alerts.setStyleSheet(
                f"QPushButton {{ color: #FFFFFF; background: {DOWN}; border: none; border-radius: 14px; font-weight: 700; }}"
            )
        else:
            self.alerts.setStyleSheet(
                "QPushButton { color: #1A1A1A; background: rgba(0,0,0,16); border: none; border-radius: 14px; }"
            )

    def set_phase(self, phase: str, failed: bool = False, urgent: int = 0) -> None:
        self.to_desk.setVisible(phase == "morning")
        self.close_button.setVisible(phase == "desk")
        self.next_button.setVisible(phase in ("evening", "gameover"))
        if phase == "morning":
            self.to_desk.setText("Open the day" if urgent == 0 else f"Open the day ({urgent})")
        self.next_button.setText("Back to the front" if failed else "Next morning")


class AlertsDrawer(QFrame):
    open_inbox = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("alertsDrawer")
        self.setFixedWidth(320)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)
        self.clock = _lab("11:00", 28, QFont.Weight.Bold)
        self.meta = _lab("Monday  ·  Day 1  ·  Morning", 12, color=HQ_MUTED)
        layout.addWidget(self.clock)
        layout.addWidget(self.meta)
        self.stats = QHBoxLayout()
        layout.addLayout(self.stats)
        layout.addWidget(_lab("NOTIFICATIONS", 10, QFont.Weight.DemiBold, HQ_MUTED))
        self.feed = QVBoxLayout()
        self.feed.setSpacing(8)
        layout.addLayout(self.feed)
        layout.addStretch(1)
        more = QPushButton("Open Inbox")
        more.setObjectName("quiet")
        more.clicked.connect(self.open_inbox.emit)
        layout.addWidget(more)

    def set_header(self, clock: str, meta: str, cash: str, urgent: int, reviews: str, cash_tip: str | None = None) -> None:
        self.clock.setText(clock)
        self.meta.setText(meta)
        self._cash_tip = cash_tip or cash
        while self.stats.count():
            item = self.stats.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        for caption, value in (("Drawer", cash), ("Urgent", str(urgent)), ("Reviews", reviews)):
            col = QVBoxLayout()
            col.setSpacing(0)
            col.addWidget(_lab(caption, 10, QFont.Weight.DemiBold, HQ_MUTED))
            figure = _lab(value, 14, QFont.Weight.DemiBold)
            if caption == "Drawer":
                figure.setToolTip(getattr(self, "_cash_tip", None) or cash)
            col.addWidget(figure)
            wrap = QWidget()
            wrap.setLayout(col)
            self.stats.addWidget(wrap)

    def set_notes(self, notes: list[tuple[bool, str, str, list]]) -> None:
        while self.feed.count():
            item = self.feed.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        if not notes:
            self.feed.addWidget(_lab("The desk is clear.", 13, color=HQ_MUTED))
            return
        from open_late.ui.theme import DOWN as DOWN_COLOR
        for urgent, title, body, actions in notes[:5]:
            card = QFrame()
            card.setObjectName("noteCard")
            box = QVBoxLayout(card)
            box.setContentsMargins(10, 8, 10, 8)
            box.setSpacing(4)
            box.addWidget(_lab("Urgent" if urgent else "Note", 10, QFont.Weight.DemiBold, DOWN_COLOR if urgent else HQ_MUTED))
            box.addWidget(_lab(title, 13, QFont.Weight.DemiBold))
            snippet = body.split(".")[0].strip()
            if snippet and not snippet.endswith("."):
                snippet += "."
            note = _lab(snippet, 11, color=HQ_MUTED)
            note.setWordWrap(True)
            box.addWidget(note)
            if actions:
                row = QHBoxLayout()
                for index, (label, slot) in enumerate(actions[:2]):
                    btn = QPushButton(label)
                    if index != 0:
                        btn.setObjectName("quiet")
                    btn.setMinimumHeight(26)
                    btn.clicked.connect(slot)
                    row.addWidget(btn)
                row.addStretch(1)
                box.addLayout(row)
            self.feed.addWidget(card)


class HQShell(QFrame):
    open_app = Signal(str)
    open_floor = Signal()
    close_day = Signal()
    next_morning = Signal()
    new_shop = Signal()
    save_now = Signal()
    front_door = Signal()
    help = Signal()
    scope_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("hqShell")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(hq_stylesheet())
        self.host = None
        self.scope = ("all", None)
        self.current_id = "home"
        self._corporate = False
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.rail = Rail()
        layout.addWidget(self.rail)
        right = QWidget()
        right.setObjectName("hqMain")
        column = QVBoxLayout(right)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        self.topbar = TopBar()
        column.addWidget(self.topbar)
        self.body = QWidget()
        self.body.setObjectName("hqBody")
        body_layout = QVBoxLayout(self.body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget()
        self.stack.setObjectName("hqPages")
        body_layout.addWidget(self.stack)
        column.addWidget(self.body, stretch=1)
        layout.addWidget(right, stretch=1)

        self.home = DashboardPage()
        self.stores = StoresPage()
        self.pos_page = PosPage()
        self.planogram = PlanogramPage()
        self.economy = EconomyPage()
        self.help_page = QScrollArea()
        self.help_page.setWidgetResizable(True)
        self.help_page.setFrameShape(QFrame.Shape.NoFrame)
        self.help_page.setObjectName("helpPage")
        help_inner = QWidget()
        help_box = QVBoxLayout(help_inner)
        help_box.setContentsMargins(22, 16, 22, 20)
        title = QLabel("How the desk works")
        title.setFont(ui_font(20, QFont.Weight.DemiBold))
        body = QLabel(HELP.strip())
        body.setWordWrap(True)
        body.setFont(ui_font(13))
        body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        help_box.addWidget(title)
        help_box.addWidget(body)
        help_box.addStretch(1)
        self.help_page.setWidget(help_inner)
        self.module_scroll = QScrollArea()
        self.module_scroll.setWidgetResizable(True)
        self.module_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.module_scroll.setObjectName("modulePage")
        self.module_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.module_inner = QWidget()
        self.module_inner.setObjectName("windowInner")
        self.module_layout = QVBoxLayout(self.module_inner)
        self.module_layout.setContentsMargins(16, 10, 22, 16)
        self.module_layout.setSpacing(10)
        self.module_scroll.setWidget(self.module_inner)

        for page in (self.home, self.stores, self.pos_page, self.planogram, self.economy, self.help_page, self.module_scroll):
            self.stack.addWidget(page)

        self.center = AlertsDrawer(self)
        self.center.hide()
        self.center.open_inbox.connect(lambda: self.open_app.emit("journal"))

        self.status = QLabel(self)
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        self.status.hide()

        # Aliases used by MainWindow and older tests.
        self.to_desk = self.topbar.to_desk
        self.close_button = self.topbar.close_button
        self.next_button = self.topbar.next_button

        self.rail.open_app.connect(self.open_app)
        self.rail.help.connect(self.help)
        self.rail.save_now.connect(self.save_now)
        self.rail.front_door.connect(self.front_door)
        self.topbar.open_floor.connect(self.open_floor)
        self.topbar.close_day.connect(self.close_day)
        self.topbar.next_morning.connect(self.next_morning)
        self.topbar.open_alerts.connect(self.toggle_center)
        self.topbar.scope_changed.connect(self._on_scope)

    def set_host(self, host) -> None:
        self.host = host
        self.home.host = host
        self.stores.host = host
        self.pos_page.host = host
        self.planogram.host = host
        self.economy.host = host
        if not getattr(self, "_search_wired", False):
            self.topbar.search.textChanged.connect(self.stores.set_query)
            self._search_wired = True
        self.set_chain_chrome(host.state if host is not None else None)

    def _on_scope(self, kind: str, scope_id) -> None:
        self.set_scope(kind, scope_id)

    def set_scope(self, kind: str, scope_id: str | None = None, silent: bool = False) -> None:
        self.scope = (kind, scope_id)
        state = self.host.state if self.host is not None else None
        self.topbar.set_scope_label(kind, scope_id, state)
        self._update_breadcrumb()
        if not silent:
            self.scope_changed.emit()

    def scope_text(self) -> str:
        kind, scope_id = self.scope
        state = self.host.state if self.host is not None else None
        if kind == "region" and scope_id:
            return scope_id
        if kind == "store" and scope_id and state is not None:
            door = next((item for item in state.doors if item.id == scope_id), None)
            if door is not None:
                return f"{door.city}, {door.state_name}"
            return state.shop_name
        return "All stores"

    def _update_breadcrumb(self) -> None:
        self.topbar.set_breadcrumb(rail_label(self.current_id, self._corporate), self.scope_text())

    def _fill_surface(self, widget, color: str, *, auto: bool = True) -> None:
        if widget is None:
            return
        widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        pal = widget.palette()
        fill = QColor(color)
        pal.setColor(QPalette.ColorRole.Window, fill)
        pal.setColor(QPalette.ColorRole.Base, fill)
        widget.setPalette(pal)
        widget.setAutoFillBackground(auto)

    def _recolor_topbar_labels(self, dark: bool) -> None:
        ink = DASH_TEXT if dark else HQ_TITLE
        muted = DASH_MUTED if dark else HQ_MUTED
        colors = {
            "chainName": ink,
            "breadcrumb": muted,
            "trayCash": ink,
            "dayChip": muted,
        }
        for name, color in colors.items():
            lab = self.topbar.findChild(QLabel, name)
            if lab is not None:
                lab.setStyleSheet(f"color: {color}; background: transparent;")

    def set_dashboard_chrome(self, dark: bool) -> None:
        self._dash_dark = bool(dark)
        main = self.findChild(QWidget, "hqMain")
        canvas = DASH_BG if dark else HQ_CANVAS
        top_fill = DASH_BG if dark else "#FFFFFF"
        for widget in (self, self.topbar, self.body, main, self.stack, self.home, getattr(self, "economy", None)):
            if widget is None:
                continue
            widget.setProperty("dashDark", "true" if dark else "false")
        # Paint the surfaces directly so a light ancestor rule cannot leak through.
        self._fill_surface(self, canvas)
        self._fill_surface(main, canvas)
        self._fill_surface(self.body, canvas)
        self._fill_surface(self.stack, canvas)
        self._fill_surface(self.topbar, top_fill)
        self._fill_surface(self.home, DASH_BG if dark else HQ_CANVAS)
        self._fill_surface(getattr(self, "economy", None), DASH_BG if dark else HQ_CANVAS)
        # Rail stays navy either way.
        self._fill_surface(self.rail, RAIL)
        if dark:
            self.setStyleSheet(hq_stylesheet() + dash_chrome_stylesheet())
        else:
            self.setStyleSheet(hq_stylesheet())
        for widget in (self, self.topbar, self.body, main, self.stack, self.home, getattr(self, "economy", None), self.rail):
            if widget is None:
                continue
            widget.style().unpolish(widget)
            widget.style().polish(widget)
            widget.update()
        self._recolor_topbar_labels(dark)

    def set_chain_chrome(self, state) -> None:
        self.topbar.set_chain(chain_info(state) if state is not None else {"id": "megamart", "name": "MegaMart", "logo": "megamart.png"})

    def set_corporate(self, corporate: bool) -> None:

        self._corporate = corporate
        self.rail.set_corporate(corporate)

    def show_page(self, app_id: str) -> None:
        # Shop starts label this rail item "Expansion"; it must not open Planogram.
        if app_id in ("expansion", "planograms") and not self._corporate:
            mapped = "expansion"
        else:
            mapped = {"overview": "home", "expansion": "stores"}.get(app_id, app_id)
        self.current_id = mapped
        if mapped == "home":
            self.stack.setCurrentWidget(self.home)
            self.home.rebuild()
        elif mapped == "stores":
            self.stack.setCurrentWidget(self.stores)
            self.stores.rebuild()
        elif mapped == "pos":
            self.stack.setCurrentWidget(self.pos_page)
            self.pos_page.rebuild()
        elif mapped == "planograms":
            self.stack.setCurrentWidget(self.planogram)
            self.planogram.rebuild()
        elif mapped == "economy":
            self.stack.setCurrentWidget(self.economy)
            self.economy.rebuild()
        elif mapped == "help":
            self.stack.setCurrentWidget(self.help_page)
        else:
            self.stack.setCurrentWidget(self.module_scroll)
        # Keep the Expansion / Planograms rail button lit in either mode.
        self.rail.set_active("planograms" if mapped == "expansion" else mapped)
        self.set_dashboard_chrome(mapped in ("home", "economy"))
        self._update_breadcrumb()
        self.lift_chrome()

    def current_page(self) -> str:
        return self.current_id

    def clear_module(self) -> QVBoxLayout:
        layout = self.module_layout
        while layout.count():
            item = layout.takeAt(0)
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
        return layout

    def layout_chrome(self) -> None:
        compact = self.width() < 1180
        self.rail.set_compact(compact)
        if self.stores.drawer is not None:
            self.stores.drawer.setFixedWidth(260 if compact else 320)
        if self.center.isVisible():
            self._place_center()
        self.lift_chrome()

    def lift_chrome(self) -> None:
        if self.center.isVisible():
            self.center.raise_()
        if self.status.isVisible():
            self.status.raise_()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.layout_chrome()

    def _place_center(self) -> None:
        height = min(self.height() - 56, 620)
        self.center.setFixedHeight(max(320, height))
        self.center.move(self.width() - self.center.width() - 12, 56)

    def toggle_center(self) -> None:
        if self.center.isVisible():
            self.center.hide()
        else:
            self._place_center()
            self.center.show()
        self.lift_chrome()

    def toggle_menu(self) -> None:
        # Compatibility no-op for older tests: the start menu is gone.
        if self.center.isVisible():
            self.center.hide()

    def hide_overlays(self) -> None:
        self.center.hide()

    def work_area(self):
        from PySide6.QtCore import QRect
        left = self.rail.width()
        return QRect(left, 48, max(480, self.width() - left), max(300, self.height() - 48))
