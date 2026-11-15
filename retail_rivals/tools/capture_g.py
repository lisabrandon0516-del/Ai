#!/usr/bin/env python3
"""Capture Concept G screens in all three modes at 1366 and 1100."""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication

from open_late.engine import answer, blocking
from open_late.store import SaveStore
from open_late.ui.shell import HelpDialog
from open_late.ui.window import MainWindow

OUT = Path("/workspace/toys_n_us_shots_g")
SIZES = [(1366, 768), (1100, 720)]
MODES = ("shop", "online", "corporate")


def grab(window: MainWindow, app: QApplication, name: str) -> None:
    app.processEvents()
    path = OUT / f"{name}.png"
    window.grab().save(str(path), "PNG")
    print(f"wrote {path.name}  {path.stat().st_size}")


def start_game(window: MainWindow, app: QApplication, mode: str, name: str) -> None:
    window._show_setup()
    app.processEvents()
    window.name_input.setText(name)
    window.shop_radio.setChecked(mode == "shop")
    window.online_radio.setChecked(mode == "online")
    window.corporate_radio.setChecked(mode == "corporate")
    window.age_check.setChecked(True)
    window._start()
    app.processEvents()


def clear_blockers(window: MainWindow) -> None:
    if window.state is None:
        return
    for message in list(blocking(window.state)):
        if message.choices:
            answer(window.state, message.id, message.choices[0].id)


def shoot_mode(window: MainWindow, app: QApplication, mode: str, width: int, height: int) -> None:
    tag = f"{mode}_{width}"
    window.resize(width, height)
    app.processEvents()

    window._front()
    app.processEvents()
    window.resize(width, height)
    grab(window, app, f"{tag}_title")

    window._show_setup()
    window.resize(width, height)
    grab(window, app, f"{tag}_setup")

    start_game(window, app, mode, {"shop": "Side Street", "online": "Night Post", "corporate": "Toy's N Us"}[mode])
    window.resize(width, height)
    grab(window, app, f"{tag}_morning")

    if window.desktop is not None:
        window.desktop.toggle_menu()
        grab(window, app, f"{tag}_start")
        window.desktop.menu.hide()
        window.desktop.toggle_center()
        grab(window, app, f"{tag}_notifications")
        window.desktop.center.hide()
        app.processEvents()

    dialog = HelpDialog(window)
    dialog.show()
    app.processEvents()
    dialog.grab().save(str(OUT / f"{tag}_help.png"), "PNG")
    print(f"wrote {tag}_help.png")
    dialog.close()

    window._to_desk()
    window.resize(width, height)
    app.processEvents()
    pages = [
        ("overview", 0),
        ("sales", 1),
        ("inventory", 2),
        ("orders", 3),
        ("staff", 4),
        ("customers", 5),
        ("marketing", 6),
        ("books", 7),
        ("stores" if mode == "corporate" else "expansion", 8),
        ("market", 9),
        ("journal", 10),
        ("settings", 11),
    ]
    for name, index in pages:
        window._goto(index)
        window.resize(width, height)
        app.processEvents()
        grab(window, app, f"{tag}_{name}")

    window._open_app("overview")
    window._open_app("inventory")
    window._open_app("staff")
    window.resize(width, height)
    grab(window, app, f"{tag}_overlap")

    clear_blockers(window)
    window._save()
    window._close()
    window.resize(width, height)
    app.processEvents()
    if window.state and window.state.phase in ("evening", "gameover"):
        grab(window, app, f"{tag}_evening")
        if not window.state.failed:
            window._next()
            window.resize(width, height)
            grab(window, app, f"{tag}_morning2")
    else:
        grab(window, app, f"{tag}_close_blocked")

    window._front()
    window.resize(width, height)
    grab(window, app, f"{tag}_title_saved")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    for width, height in SIZES:
        for mode in MODES:
            db = Path("/tmp") / f"tnu_g_{mode}_{width}.sqlite"
            if db.exists():
                db.unlink()
            window = MainWindow(SaveStore(db))
            window.show()
            window.resize(width, height)
            app.processEvents()
            shoot_mode(window, app, mode, width, height)
            window.close()
            app.processEvents()


if __name__ == "__main__":
    main()
