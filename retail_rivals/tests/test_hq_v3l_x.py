"""HQ v3l: planogram push, lease picker, Expansion page, inventory toast, floor tools."""

from __future__ import annotations

from PySide6.QtCore import QRect, Qt
from PySide6.QtWidgets import QApplication, QComboBox, QDialog, QSpinBox, QWidget

from open_late.corporate import openable_markets
from open_late.engine import order_qty_max
from open_late.store import SaveStore
from open_late.ui.hq_pages import LeasePickerDialog
from open_late.ui.hq_planogram import shares_for_door, template_shares
from open_late.ui.window import MainWindow
import open_late.ui.hq_planogram as planogram_mod


def _app(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


def _boot(tmp_path, monkeypatch, *, mode="corporate", size=(1366, 768)):
    app = _app(monkeypatch)
    window = MainWindow(SaveStore(tmp_path / "saves.sqlite"))
    window.show()
    window.setMinimumSize(1, 1)
    window.resize(*size)
    app.processEvents()
    window._show_setup()
    window.name_input.setText("Retail Rivals")
    if mode == "corporate":
        window.corporate_radio.setChecked(True)
        window._chosen_chain_id = "bluestar"
        window._chosen_economy = "standard"
    else:
        window.shop_radio.setChecked(True)
    window.age_check.setChecked(True)
    window._start()
    app.processEvents()
    window._to_desk()
    app.processEvents()
    return app, window


def _desktop_rect(widget, desktop) -> QRect:
    return QRect(widget.mapTo(desktop, widget.rect().topLeft()), widget.size())


def test_push_to_stores_calls_set_planogram(tmp_path, monkeypatch):
    app, window = _boot(tmp_path, monkeypatch, mode="corporate")
    calls = []
    real = planogram_mod.set_planogram

    def wrapped(state, door_id, shares):
        payload = dict(shares)
        calls.append((door_id, payload))
        return real(state, door_id, payload)

    monkeypatch.setattr(planogram_mod, "set_planogram", wrapped)
    window._open_app("planograms")
    app.processEvents()
    page = window.desktop.planogram
    assert page.isVisible()
    page._set_template("grocery")
    app.processEvents()
    shares = template_shares("grocery", window.state)
    assert sum(shares.values()) == 100
    page._push()
    app.processEvents()
    assert calls, "Push to stores must call set_planogram"
    ids = {door.id for door in window.state.doors}
    called = {door_id for door_id, _shares in calls}
    assert called == ids
    for door in window.state.doors:
        expected = shares_for_door(shares, door)
        assert door.planogram == expected
        assert door.planogram_days == 0
    note = window.status.text().lower()
    assert "planogram pushed" in note or "the wall adds up" in note
    window.close()


def test_blank_template_does_not_push(tmp_path, monkeypatch):
    app, window = _boot(tmp_path, monkeypatch, mode="corporate")
    calls = []
    real = planogram_mod.set_planogram

    def wrapped(state, door_id, shares):
        calls.append(door_id)
        return real(state, door_id, shares)

    monkeypatch.setattr(planogram_mod, "set_planogram", wrapped)
    window._open_app("planograms")
    app.processEvents()
    page = window.desktop.planogram
    page._set_template("blank")
    app.processEvents()
    before = [dict(door.planogram) for door in window.state.doors]
    page._push()
    app.processEvents()
    assert calls == []
    assert [dict(door.planogram) for door in window.state.doors] == before
    assert "no facings" in window.status.text().lower()
    window.close()


def test_lease_picker_signs_chosen_city_only_after_confirm(tmp_path, monkeypatch):
    app, window = _boot(tmp_path, monkeypatch, mode="corporate")
    window.state.cash = 50_000_000
    window._open_app("stores")
    app.processEvents()
    available = openable_markets(window.state)
    assert len(available) >= 2
    first = available[0].id
    second = available[1].id
    owned = {door.id for door in window.state.doors}

    def reject(self):
        self.list.setCurrentRow(0)
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(LeasePickerDialog, "exec", reject)
    window.desktop.stores._sign_prompt()
    app.processEvents()
    assert {door.id for door in window.state.doors} == owned

    def accept_second(self):
        for row in range(self.list.count()):
            item = self.list.item(row)
            if item is not None and item.data(Qt.ItemDataRole.UserRole) == second:
                self.list.setCurrentRow(row)
                break
        assert self.selected_market_id() == second
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(LeasePickerDialog, "exec", accept_second)
    window.desktop.stores._sign_prompt(first)
    app.processEvents()
    ids = {door.id for door in window.state.doors}
    assert second in ids
    assert first not in ids
    assert first not in owned
    window.close()


def test_expansion_rail_opens_expansion_page_for_shop(tmp_path, monkeypatch):
    app, window = _boot(tmp_path, monkeypatch, mode="shop")
    window._open_app("planograms")
    app.processEvents()
    desktop = window.desktop
    assert desktop.current_page() == "expansion"
    assert desktop.module_scroll.isVisible()
    assert not desktop.planogram.isVisible()
    from PySide6.QtWidgets import QLabel, QPushButton
    text = "\n".join(
        child.text()
        for child in desktop.module_scroll.findChildren(QLabel) + desktop.module_scroll.findChildren(QPushButton)
    )
    assert "Expansion" in text
    assert "Planogram Editor" not in text
    window._open_app("expansion")
    app.processEvents()
    assert desktop.current_page() == "expansion"
    assert desktop.module_scroll.isVisible()
    window.close()


def test_corporate_planograms_rail_still_opens_editor(tmp_path, monkeypatch):
    app, window = _boot(tmp_path, monkeypatch, mode="corporate")
    window._open_app("planograms")
    app.processEvents()
    assert window.desktop.current_page() == "planograms"
    assert window.desktop.planogram.isVisible()
    window.close()


def test_quantities_filled_toast_does_not_cover_supplier_row(tmp_path, monkeypatch):
    app, window = _boot(tmp_path, monkeypatch, mode="shop")
    window._open_app("inventory")
    app.processEvents()
    combo = window.desktop.findChild(QComboBox, "supplierCombo")
    assert combo is not None
    window._suggest()
    app.processEvents()
    status = window.status
    assert status.isVisible()
    assert "Quantities filled" in status.text()
    desktop = window.desktop
    status_rect = QRect(status.pos(), status.size())
    combo_rect = _desktop_rect(combo, desktop)
    assert not status_rect.intersects(combo_rect), (status_rect, combo_rect)
    assert status.y() >= desktop.height() // 2
    assert status_rect.bottom() <= desktop.height()
    window.close()


def test_hours_page_has_per_city_controls(tmp_path, monkeypatch):
    app, window = _boot(tmp_path, monkeypatch, mode="corporate")
    window._open_app("settings")
    app.processEvents()
    door = window.state.doors[0]
    open_spin = window.findChild(QSpinBox, f"doorOpen_{door.id}")
    close_spin = window.findChild(QSpinBox, f"doorClose_{door.id}")
    assert open_spin is not None and close_spin is not None
    window.close()


def test_store_drawer_has_floor_tools_and_truck_uses_order_qty_max(tmp_path, monkeypatch):
    app, window = _boot(tmp_path, monkeypatch, mode="corporate")
    window._open_app("stores")
    app.processEvents()
    page = window.desktop.stores
    if not page.selected and window.state.doors:
        page.select_store(window.state.doors[0].id)
        app.processEvents()
    labor = page.findChild(QSpinBox, "laborBudget")
    weeks = page.findChild(QSpinBox, "weeksSupply")
    qty = page.findChild(QSpinBox, "truckQty")
    assert labor is not None and weeks is not None and qty is not None
    assert qty.maximum() == order_qty_max()
    page._toggle_profile()
    app.processEvents()
    assert page.findChild(QWidget, "sendWall") is not None
    window.close()
