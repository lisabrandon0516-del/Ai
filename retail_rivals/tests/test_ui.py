"""The desk opens, a day can be closed, and the charts draw."""

from __future__ import annotations

import os

from PySide6.QtWidgets import QApplication

from open_late.store import SaveStore
from open_late.ui.window import MainWindow


def test_desk_runs_a_day(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    db = tmp_path / "saves.sqlite"
    app = QApplication.instance() or QApplication([])
    window = MainWindow(SaveStore(db))
    window.show()
    app.processEvents()

    window._show_setup()
    window.name_input.setText("Ledger")
    window.shop_radio.setChecked(True)
    window.age_check.setChecked(True)
    window._start()
    app.processEvents()
    assert window.state is not None
    assert window.state.phase == "morning"
    assert window.state.shop_name == "Ledger"
    window.grab().save(str(tmp_path / "morning.png"))

    window._to_desk()
    app.processEvents()
    assert window.state.phase == "desk"
    window._suggest()
    window._place()
    app.processEvents()
    window.grab().save(str(tmp_path / "desk.png"))

    window._close()
    app.processEvents()
    assert window.state.phase == "evening"
    assert window.state.last_report.day == 1
    assert window.state.last_report.visits > 0
    window.grab().save(str(tmp_path / "evening.png"))

    window._next()
    app.processEvents()
    assert window.state.day == 2
    assert window.state.phase == "morning"
    assert (tmp_path / "morning.png").stat().st_size > 1000
    assert (tmp_path / "desk.png").stat().st_size > 1000
    assert (tmp_path / "evening.png").stat().st_size > 1000

    listed = SaveStore(db).list_saves()
    assert listed and listed[0][1] == "Ledger"
    os.environ.pop("QT_QPA_PLATFORM", None)
    window.close()


def test_corporate_desk_opens_the_stores(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    db = tmp_path / "saves.sqlite"
    app = QApplication.instance() or QApplication([])
    window = MainWindow(SaveStore(db))
    window.show()
    app.processEvents()
    window._show_setup()
    window.name_input.setText("Toy's N Us")
    window.corporate_radio.setChecked(True)
    window.age_check.setChecked(True)
    window._start()
    app.processEvents()
    assert window.state is not None
    assert window.state.mode == "corporate"
    assert window.state.doors[0].city == "Evansville"
    window._desk_index = 8
    window._to_desk()
    app.processEvents()
    assert window.state.phase == "desk"
    window.grab().save(str(tmp_path / "stores.png"))
    window._goto(4)
    app.processEvents()
    window.grab().save(str(tmp_path / "managers.png"))
    window._close()
    app.processEvents()
    assert window.state.phase == "evening"
    assert window.state.last_report.revenue > 0
    assert (tmp_path / "stores.png").stat().st_size > 1000
    window.close()

def test_window_manager_opens_and_closes(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from open_late.ui.icons import APPS, app_id_for_index
    from open_late.ui.theme import ACCENT, DOWN

    db = tmp_path / "saves.sqlite"
    app = QApplication.instance() or QApplication([])
    window = MainWindow(SaveStore(db))
    window.show()
    window.resize(1366, 768)
    app.processEvents()
    window._show_setup()
    window.name_input.setText("Ledger")
    window.shop_radio.setChecked(True)
    window.age_check.setChecked(True)
    window._start()
    app.processEvents()

    assert window.desktop is not None
    desktop = window.desktop
    # Morning opens Home in the single HQ pane.
    assert desktop.current_page() == "home"
    assert desktop.home.isVisible()

    # Opening the floor, then every desk app, must show a page in the shell.
    window._to_desk()
    app.processEvents()
    mapped = {"overview": "home"}
    for _app_id, _label, _g, desk_index in APPS:
        window._goto(desk_index)
        app.processEvents()
        app_id = mapped.get(app_id_for_index(desk_index), app_id_for_index(desk_index))
        assert desktop.current_page() == app_id, app_id

    # Alerts drawer toggles without breaking the desk.
    desktop.toggle_center()
    app.processEvents()
    assert desktop.center.isVisible()
    desktop.toggle_center()
    app.processEvents()
    assert not desktop.center.isVisible()
    desktop.toggle_menu()
    app.processEvents()

    # Falling metrics use the down color, never the primary action blue.
    assert DOWN.lower() != ACCENT.lower()
    assert DOWN == "#C42B1C"
    window.close()


def test_desk_fits_the_1100_minimum(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    db = tmp_path / "saves.sqlite"
    app = QApplication.instance() or QApplication([])
    window = MainWindow(SaveStore(db))
    window.show()
    window.resize(1100, 720)
    app.processEvents()
    window._show_setup()
    window.name_input.setText("Narrow")
    window.shop_radio.setChecked(True)
    window.age_check.setChecked(True)
    window._start()
    app.processEvents()
    window._to_desk()
    window._goto(2)  # inventory
    app.processEvents()
    desktop = window.desktop
    assert desktop.width() == 1100
    assert desktop.current_page() == "inventory"
    assert desktop.module_scroll.isVisible()
    # Inventory stays inside the work area and does not hang off the shell.
    area = desktop.work_area()
    assert area.width() >= 480
    assert area.right() <= 1100
    assert area.bottom() <= 720
    window.close()
