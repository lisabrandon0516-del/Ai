"""Concept G mica desk: light acrylic, cool type, and a down color that is never the action blue."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QColor, QFont, QFontDatabase

ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "assets" / "fonts"

# Action / brand blue — never used for a falling metric.
ACCENT = "#0B6CBD"
ACCENT_TEXT = "#FFFFFF"
UP = "#0F7B0F"
DOWN = "#C42B1C"
URGENT = "#C42B1C"
TEXT = "#1A1A1A"
MUTED = "#5C5C5C"
FAINT = "#7A7A7A"

PAINT = {
    "text": QColor(TEXT),
    "muted": QColor(MUTED),
    "faint": QColor(FAINT),
    "accent": QColor(ACCENT),
    "up": QColor(UP),
    "down": QColor(DOWN),
    "urgent": QColor(URGENT),
    "spark_up": QColor(UP),
    "spark_down": QColor(DOWN),
    "spark_neutral": QColor(ACCENT),
    "track": QColor("#E4E7EC"),
    "hole": QColor("#F4F6FA"),
    "grid": QColor(0, 0, 0, 28),
    "fill_top": QColor(255, 255, 255, 238),
    "fill_bottom": QColor(246, 248, 252, 228),
    "border": QColor(255, 255, 255, 220),
    "shadow": QColor(20, 30, 50, 80),
    "hairline": QColor(0, 0, 0, 32),
}


def load_fonts() -> str:
    """Load bundled Selawik and return the UI family, with a safe fallback."""
    family = "Selawik"
    if FONTS.exists():
        for name in ("selawk.ttf", "selawksb.ttf", "selawkb.ttf", "selawkl.ttf", "selawksl.ttf"):
            path = FONTS / name
            if path.exists():
                QFontDatabase.addApplicationFont(str(path))
    available = set(QFontDatabase.families())
    if family not in available:
        for candidate in ("Segoe UI", "Liberation Sans", "Cantarell", "Arial"):
            if candidate in available:
                return candidate
        return "sans-serif"
    return family


def ui_font(size: int = 13, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    font = QFont(_FAMILY)
    font.setPixelSize(size)
    font.setWeight(weight)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    return font


# Filled after load_fonts() is called from MainWindow / main.
_FAMILY = "Selawik"


def set_family(name: str) -> None:
    global _FAMILY
    _FAMILY = name


def stylesheet(family: str | None = None) -> str:
    face = family or _FAMILY
    brand = (FONTS.parent / "brand").as_posix()
    radio_off = f"{brand}/radio_off.png"
    radio_on = f"{brand}/radio_on.png"
    return f"""
    * {{
        font-family: "{face}", "Segoe UI", "Liberation Sans", sans-serif;
    }}
    QMainWindow, QWidget#shell, QStackedWidget#pages {{
        background: #D7E3F0;
        color: {TEXT};
    }}
    QMenuBar {{
        background: transparent;
        color: {TEXT};
    }}
    QLabel {{
        color: {TEXT};
        background: transparent;
    }}
    QLabel#kicker, QLabel#figureCaption {{
        color: {FAINT};
        font-size: 11px;
        font-weight: 600;
        letter-spacing: 0.8px;
    }}
    QLabel#wordmark, QLabel#logo {{
        background: transparent;
    }}
    QLabel#deck, QLabel#quiet, QLabel#hint, QLabel#meta {{
        color: {MUTED};
        font-size: 13px;
    }}
    QLabel#section {{
        color: {TEXT};
        font-size: 13px;
        font-weight: 600;
    }}
    QLabel#cardTitle {{
        color: {TEXT};
        font-size: 15px;
        font-weight: 600;
    }}
    QLabel#urgent {{
        color: {URGENT};
        font-weight: 600;
    }}
    QLabel#chip, QLabel#avatar {{
        background: rgba(11, 108, 189, 0.12);
        color: {TEXT};
        border: 1px solid rgba(11, 108, 189, 0.25);
        border-radius: 8px;
        padding: 2px 8px;
    }}
    QLabel#up {{
        color: {UP};
        font-size: 12px;
        font-weight: 600;
    }}
    QLabel#down {{
        color: {DOWN};
        font-size: 12px;
        font-weight: 600;
    }}
    QLabel#heroValue {{
        color: {TEXT};
        font-size: 26px;
        font-weight: 700;
    }}
    QLabel#status {{
        color: {MUTED};
    }}
    QLabel#live {{
        color: {UP};
    }}
    QFrame#rule {{
        background: {ACCENT};
    }}
    QFrame#door, QFrame#card, QFrame#hero, QFrame#kpi, QFrame#figure, QFrame#stat {{
        background: rgba(255, 255, 255, 210);
        border: 1px solid rgba(0, 0, 0, 28);
        border-radius: 10px;
    }}
    QFrame#cardUrgent {{
        background: rgba(255, 255, 255, 220);
        border: 1px solid rgba(196, 43, 28, 90);
        border-radius: 10px;
    }}
    QPushButton {{
        background: {ACCENT};
        color: {ACCENT_TEXT};
        border: 1px solid rgba(255, 255, 255, 80);
        border-radius: 6px;
        padding: 7px 14px;
        font-weight: 600;
    }}
    QPushButton:hover {{
        background: #0A5CA3;
    }}
    QPushButton:disabled {{
        background: rgba(0, 0, 0, 28);
        color: #4A4A4A;
        border: 1px solid rgba(0, 0, 0, 32);
    }}
    QPushButton#quiet, QPushButton#nav, QPushButton#navOn {{
        background: rgba(0, 0, 0, 10);
        color: {TEXT};
        border: 1px solid rgba(0, 0, 0, 28);
    }}
    QPushButton#quiet:hover, QPushButton#nav:hover {{
        background: rgba(0, 0, 0, 18);
    }}
    QPushButton#navOn {{
        background: rgba(11, 108, 189, 0.16);
        border: 1px solid rgba(11, 108, 189, 0.45);
    }}
    QLineEdit, QSpinBox, QComboBox {{
        background: rgba(255, 255, 255, 230);
        color: {TEXT};
        border: 1px solid rgba(0, 0, 0, 40);
        border-radius: 6px;
        padding: 5px 8px;
        min-height: 26px;
        selection-background-color: {ACCENT};
        selection-color: {ACCENT_TEXT};
    }}
    QComboBox QAbstractItemView {{
        background: #FFFFFF;
        color: {TEXT};
        selection-background-color: {ACCENT};
        selection-color: {ACCENT_TEXT};
    }}
    QCheckBox, QRadioButton {{
        color: {TEXT};
        spacing: 8px;
    }}
    QRadioButton::indicator {{
        width: 16px;
        height: 16px;
        border: none;
        background: transparent;
        image: url("{radio_off}");
    }}
    QRadioButton::indicator:checked {{
        width: 16px;
        height: 16px;
        border: none;
        background: transparent;
        image: url("{radio_on}");
    }}
    QCheckBox::indicator {{
        width: 16px;
        height: 16px;
        border-radius: 3px;
        border: 2px solid #5C5C5C;
        background: #FFFFFF;
    }}
    QCheckBox::indicator:checked {{
        background: {ACCENT};
        border: 2px solid {ACCENT};
    }}
    QFrame#noteCard {{
        background: rgba(255, 255, 255, 90);
        border: 1px solid rgba(0, 0, 0, 28);
        border-radius: 12px;
    }}
    QFrame#noteCard QLabel {{
        background: transparent;
        border: none;
    }}
    QScrollArea {{
        background: transparent;
        border: none;
    }}
    QScrollArea > QWidget > QWidget {{
        background: transparent;
    }}
    QScrollBar:vertical {{
        background: rgba(255, 255, 255, 90);
        width: 14px;
        margin: 3px;
        border-radius: 7px;
        border: 1px solid rgba(255, 255, 255, 140);
    }}
    QScrollBar::handle:vertical {{
        background: rgba(32, 44, 64, 150);
        border: 1px solid rgba(255, 255, 255, 160);
        border-radius: 6px;
        min-height: 36px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: rgba(32, 44, 64, 190);
    }}
    QScrollBar:horizontal {{
        background: rgba(255, 255, 255, 90);
        height: 14px;
        margin: 3px;
        border-radius: 7px;
        border: 1px solid rgba(255, 255, 255, 140);
    }}
    QScrollBar::handle:horizontal {{
        background: rgba(32, 44, 64, 150);
        border: 1px solid rgba(255, 255, 255, 160);
        border-radius: 6px;
        min-width: 36px;
    }}
    QScrollBar::handle:horizontal:hover {{
        background: rgba(32, 44, 64, 190);
    }}
    QScrollBar::add-line, QScrollBar::sub-line {{
        height: 0;
        width: 0;
    }}
    QTableWidget {{
        background: rgba(255, 255, 255, 160);
        color: {TEXT};
        gridline-color: rgba(0, 0, 0, 20);
        border: 1px solid rgba(0, 0, 0, 24);
        border-radius: 8px;
        alternate-background-color: rgba(0, 0, 0, 8);
    }}
    QHeaderView::section {{
        background: rgba(255, 255, 255, 200);
        color: {FAINT};
        border: none;
        border-bottom: 1px solid rgba(0, 0, 0, 24);
        padding: 6px 8px;
        font-weight: 600;
    }}
    QMessageBox {{
        background: #F4F6FA;
        color: {TEXT};
    }}
    QMessageBox QLabel {{
        color: {TEXT};
    }}
    QProgressBar {{
        background: #E4E7EC;
        border: none;
        border-radius: 4px;
        color: {TEXT};
        text-align: center;
        min-height: 12px;
    }}
    QProgressBar::chunk {{
        background: {ACCENT};
        border-radius: 4px;
    }}
    """


# Backwards-compatible name used by __main__ before fonts are loaded.
STYLESHEET = stylesheet("Selawik")

# Corporate HQ chrome. Applied on the play shell only, not the title or setup pages.
# Light canvas + navy rail, sampled from the approved store-portfolio and planogram mockups.
RAIL = "#021F3F"
RAIL_TEXT = "#E8EEF5"
RAIL_ACTIVE = "#053B83"
RR_BLUE = "#0070F0"
RR_YELLOW = "#FFC40A"
RR_YELLOW_TEXT = "#1A1A1A"
HQ_CANVAS = "#F4F6FA"
HQ_CARD = "#FFFFFF"
HQ_LINE = "#E3E7EE"
HQ_MUTED = "#5B6573"
HQ_FAINT = "#7A8492"
HQ_TITLE = "#122033"
HEAT_COOL = "#9ED0EA"
HEAT_HOT = "#E4C36A"
OPEN_GREEN = "#1F9A56"

# Dark navy dashboard (dashboard.jpg). Used only while the Dashboard page is showing.
DASH_BG = "#09152D"
DASH_CARD = "#0E1C3A"
DASH_LINE = "#1A2E55"
DASH_TEXT = "#E8EEF8"
DASH_MUTED = "#8BA0C0"
DASH_FAINT = "#6B82A8"
DASH_GLOW = "#3D7EFF"
DASH_PIN_HIGH = "#22C55E"
DASH_PIN_MID = "#F5C542"
DASH_PIN_LOW = "#EF4444"
DASH_ACCENT = "#7C5CFF"


def dash_chrome_stylesheet() -> str:
    """Overrides appended to hq_stylesheet() while the dark dashboard is up.

    These selectors are written to match or beat the light rules in
    hq_stylesheet() (same selectors, later in the sheet). The sheet is
    only attached while Dashboard is showing, so Portfolio and Planogram
    get the light chrome back when it is removed.
    """
    return f"""
    QWidget#hqShell, QWidget#hqMain, QWidget#hqBody, QStackedWidget#hqPages,
    QWidget#hqPages > QWidget, QWidget#dashboardPage, QWidget#economyPage {{
        background: {DASH_BG};
        background-color: {DASH_BG};
        color: {DASH_TEXT};
    }}
    QWidget#hqTopBar, QFrame#hqTopBar {{
        background: {DASH_BG};
        background-color: {DASH_BG};
        color: {DASH_TEXT};
        border-bottom: 1px solid {DASH_LINE};
    }}
    QWidget#hqTopBar QLabel, QFrame#hqTopBar QLabel {{
        color: {DASH_TEXT};
        background: transparent;
    }}
    QLabel#breadcrumb, QLabel#chainName, QLabel#dayChip, QLabel#trayCash {{
        color: {DASH_MUTED};
        background: transparent;
    }}
    QLabel#trayCash {{
        color: {DASH_TEXT};
    }}
    QLabel#pageTitle {{
        color: {DASH_TEXT};
    }}
    QLabel#pageDeck, QLabel#pnlNote {{
        color: {DASH_MUTED};
        background: transparent;
    }}
    QLineEdit#topSearch {{
        background: #0B1730;
        color: {DASH_TEXT};
        border: 1px solid {DASH_LINE};
        border-radius: 18px;
    }}
    QLineEdit#topSearch::placeholder {{
        color: {DASH_FAINT};
    }}
    QPushButton#scopeBtn, QPushButton#scopeBtnOn {{
        background: #0B1730;
        color: {DASH_TEXT};
        border: 1px solid {DASH_LINE};
    }}
    QFrame#chainChip {{
        background: #0B1730;
        border: 1px solid {DASH_LINE};
    }}
    QPushButton#alertsBtn {{
        background: #0B1730;
        color: {DASH_TEXT};
        border: 1px solid {DASH_LINE};
        border-radius: 14px;
    }}
    QFrame#economyStrip {{
        background: {DASH_CARD};
        border: 1px solid {DASH_LINE};
        border-radius: 14px;
    }}
    QPushButton#railNavOn {{
        background: #3A1D6E;
        color: #F3E8FF;
        border-radius: 10px;
    }}
    """


def hq_stylesheet(family: str | None = None) -> str:
    face = family or _FAMILY
    return f"""
    QWidget#hqShell {{
        background: {HQ_CANVAS};
        color: {HQ_TITLE};
        font-family: "{face}", "Segoe UI", "Liberation Sans", sans-serif;
    }}
    QWidget#hqMain, QWidget#hqBody, QStackedWidget#hqPages, QWidget#hqPages > QWidget {{
        background: {HQ_CANVAS};
        color: {HQ_TITLE};
    }}
    QFrame#hqRail, QWidget#hqRail, QWidget#hqRail QScrollArea, QWidget#hqRail QScrollArea > QWidget, QWidget#railNavHost {{
        background: {RAIL};
        background-color: {RAIL};
        color: {RAIL_TEXT};
    }}
    QLabel#railLogo, QLabel#railChainName {{
        color: {RAIL_TEXT};
        background: transparent;
    }}
    QPushButton#railNav, QPushButton#railNavOn, QPushButton#railQuiet {{
        background: transparent;
        color: {RAIL_TEXT};
        border: none;
        border-radius: 8px;
        text-align: left;
        padding: 3px 8px;
        font-weight: 600;
        font-size: 12px;
    }}
    QWidget#railFooter QPushButton#railQuiet {{
        text-align: center;
        padding: 3px 2px;
        font-size: 11px;
    }}
    QPushButton#railNav:hover, QPushButton#railQuiet:hover {{
        background: rgba(255, 255, 255, 16);
    }}
    QPushButton#railNavOn {{
        background: {RAIL_ACTIVE};
        color: #FFFFFF;
        border-left: 3px solid {RR_YELLOW};
        padding-left: 9px;
    }}
    QWidget#hqTopBar {{
        background: #FFFFFF;
        color: {HQ_TITLE};
        border-bottom: 1px solid {HQ_LINE};
    }}
    QWidget#hqTopBar QLabel {{
        color: {HQ_TITLE};
        background: transparent;
    }}
    QLineEdit#topSearch {{
        background: #FFFFFF;
        color: {HQ_TITLE};
        border: 1px solid {HQ_LINE};
        border-radius: 18px;
        padding: 6px 14px;
        min-height: 28px;
        selection-background-color: {RR_BLUE};
    }}
    QPushButton#scopeBtn, QPushButton#scopeBtnOn {{
        background: #FFFFFF;
        color: {HQ_TITLE};
        border: 1px solid {HQ_LINE};
        border-radius: 8px;
        padding: 5px 12px;
        font-weight: 600;
        text-align: left;
    }}
    QFrame#chainChip {{
        background: #FFFFFF;
        border: 1px solid {HQ_LINE};
        border-radius: 8px;
    }}
    QLabel#breadcrumb {{
        color: {HQ_MUTED};
        font-size: 12px;
    }}
    QLabel#pageTitle {{
        color: {HQ_TITLE};
        font-weight: 700;
    }}
    QLabel#pageDeck {{
        color: {HQ_MUTED};
    }}
    QFrame#storeCard, QFrame#storeCardOn, QFrame#todoRow, QFrame#drawerCard,
    QFrame#kpiTake, QFrame#kpiContribution, QFrame#kpiDrawer, QFrame#kpiSunday,
    QFrame#kpiReviews, QFrame#kpiNotes, QFrame#kpiCash, QFrame#kpiRevenue, QFrame#kpiMargin,
    QFrame#card, QFrame#todoQueue, QFrame#marketingCard, QFrame#planoPreview,
    QFrame#revenueCard, QFrame#perfCard, QFrame#mapCard {{
        background: {HQ_CARD};
        border: 1px solid {HQ_LINE};
        border-radius: 12px;
    }}
    QFrame#storeCardOn {{
        border: 1px solid rgba(11, 108, 189, 0.55);
        background: #FFFFFF;
    }}
    QFrame#storeDrawer {{
        background: #FFFFFF;
        border-left: 1px solid {HQ_LINE};
    }}
    QWidget#storeMap {{
        background: #F8F9FB;
        border: 1px solid {HQ_LINE};
        border-radius: 12px;
    }}
    QPushButton#toDesk, QPushButton#closeDay, QPushButton#nextMorning, QPushButton#signLease,
    QPushButton#primary, QPushButton#pushStores, QPushButton#viewProfile, QPushButton#startGame {{
        background: {RR_BLUE};
        color: #FFFFFF;
        border: none;
        border-bottom: 2px solid {RR_YELLOW};
        border-radius: 8px;
        padding: 8px 16px;
        font-weight: 700;
    }}
    QPushButton#toDesk:hover, QPushButton#closeDay:hover, QPushButton#nextMorning:hover,
    QPushButton#signLease:hover, QPushButton#primary:hover, QPushButton#pushStores:hover,
    QPushButton#viewProfile:hover, QPushButton#startGame:hover {{
        background: #155FE0;
        color: #FFFFFF;
    }}
    QPushButton#toDesk:disabled, QPushButton#closeDay:disabled, QPushButton#nextMorning:disabled,
    QPushButton#signLease:disabled, QPushButton#primary:disabled, QPushButton#pushStores:disabled,
    QPushButton#viewProfile:disabled, QPushButton#startGame:disabled {{
        background: #8AA0C8;
        color: #F4F6FA;
        border-bottom: 2px solid #E0E4EC;
    }}
    QLabel#placeholder, QLabel#pnlNote {{
        color: {HQ_MUTED};
        font-size: 11px;
    }}
    QWidget#alertsDrawer {{
        background: #FFFFFF;
        border: 1px solid {HQ_LINE};
        border-radius: 12px;
    }}
    QLabel#figureCaption {{
        color: {HQ_FAINT};
        font-weight: 700;
        font-size: 11px;
    }}
    QFrame#chainPickCard, QFrame#chainPickCardOn {{
        background: #FFFFFF;
        border: 1px solid {HQ_LINE};
        border-radius: 12px;
    }}
    QFrame#chainPickCardOn {{
        border: 2px solid {RR_BLUE};
    }}
    QLabel#openBadge {{
        color: #FFFFFF;
        background: {OPEN_GREEN};
        border-radius: 9px;
        padding: 1px 8px;
        font-weight: 700;
        font-size: 10px;
    }}
    QFrame#fixtureRow, QFrame#fixtureRowOn, QFrame#skuRow {{
        background: #FFFFFF;
        border: 1px solid {HQ_LINE};
        border-radius: 8px;
    }}
    QFrame#fixtureRowOn {{
        border: 1px solid {RR_BLUE};
        background: #F3F8FF;
    }}
    QPushButton#templateChip, QPushButton#templateChipOn {{
        background: #FFFFFF;
        color: {HQ_TITLE};
        border: 1px solid {HQ_LINE};
        border-radius: 14px;
        padding: 4px 12px;
        font-weight: 600;
    }}
    QPushButton#templateChipOn {{
        border: 1px solid {RR_BLUE};
        background: #E8F1FE;
        color: {RAIL_ACTIVE};
    }}
    """
