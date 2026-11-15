"""HQ v3j: larger secondary type on Planogram department chips."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication

from open_late.store import SaveStore
from open_late.text import money_compact
from open_late.ui.hq_planogram import (
    CHIP_DOLLAR_PX,
    CHIP_HEADER,
    CHIP_SECONDARY_PX,
    ShelfCanvas,
    _layout_products,
)
from open_late.ui.window import MainWindow
from tests.test_hq_v3g_x import _advance


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


def _resize(window, app, size):
    width, height = size
    window.setMinimumSize(1, 1)
    window.resize(width, height)
    app.processEvents()
    window.resize(width, height)
    app.processEvents()


def test_chip_secondary_is_one_step_up_and_dollars_stay_dominant():
    # v3i painted the name / share / move at 8px; v3j bumps that one pixel step.
    assert CHIP_SECONDARY_PX == 9
    assert CHIP_DOLLAR_PX == 10
    assert CHIP_DOLLAR_PX > CHIP_SECONDARY_PX
    # Header is tall enough for both lines plus a little padding, no overlap.
    assert CHIP_HEADER >= CHIP_DOLLAR_PX + CHIP_SECONDARY_PX + 6


def test_chips_fit_without_clipping_or_overlapping_tiles_at_both_sizes(tmp_path, monkeypatch):
    app, window = _boot(tmp_path, monkeypatch)
    _advance(window.state, 16, restock=True)
    if hasattr(window, "refresh"):
        window.refresh()
    app.processEvents()
    for size in ((1366, 768), (1100, 700)):
        _resize(window, app, size)
        window._open_app("planograms")
        app.processEvents()
        canvas = window.desktop.planogram.canvas
        pix = canvas.grab()
        assert not pix.isNull()
        assert canvas.blocks, f"expected department chips at {size}"
        for block in canvas.blocks:
            rect = block["rect"]
            assert rect.height() == CHIP_HEADER, (
                f"{block['dept']} chip height {rect.height()} != {CHIP_HEADER} at {size}"
            )
            assert rect.left() >= 0 and rect.top() >= 0
            assert rect.right() < canvas.width()
            assert rect.bottom() < canvas.height()
            assert block["primary"] == money_compact(block["sales"])
            # Chips must not cover product tiles.
            for tile in canvas.tile_rects:
                assert not rect.intersects(tile), (
                    f"{block['dept']} chip {rect.getRect()} overlaps tile {tile.getRect()} at {size}"
                )
        # Chips on the same shelf should not overlap each other.
        for i, a in enumerate(canvas.blocks):
            for b in canvas.blocks[i + 1 :]:
                assert not a["rect"].intersects(b["rect"]), (
                    f"{a['dept']} overlaps {b['dept']} at {size}"
                )
    window.close()


def test_injected_stats_use_taller_header_for_two_line_chips():
    canvas = ShelfCanvas()
    stats = {
        "grocery": {
            "sales": 12_400,
            "prior": 11_000,
            "share": 0.2,
            "delta_pct": 0.127,
            "has_prior": True,
            "store_total": 62_000,
        }
    }
    canvas.set_layout(_layout_products("balanced"), stats=stats)
    canvas.resize(800, 480)
    canvas.grab()
    grocery = [b for b in canvas.blocks if b["dept"] == "grocery"]
    assert grocery
    assert grocery[0]["rect"].height() == CHIP_HEADER
    assert grocery[0]["secondary"]
    for tile in canvas.tile_rects:
        assert not grocery[0]["rect"].intersects(tile)
