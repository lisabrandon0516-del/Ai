"""Launch the Retail Rivals desk."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from open_late.ui.theme import load_fonts, set_family, stylesheet
from open_late.ui.window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Retail Rivals")
    app.setStyle("Fusion")
    family = load_fonts()
    set_family(family)
    app.setStyleSheet(stylesheet(family))
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
