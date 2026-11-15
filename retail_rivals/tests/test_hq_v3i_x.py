"""HQ v3i: department dollar amounts on the Planogram canvas."""

from __future__ import annotations

from types import SimpleNamespace

from PySide6.QtWidgets import QApplication

from open_late.store import SaveStore
from open_late.text import money, money_compact
from open_late.ui.hq_adapter import department_week_compare
from open_late.ui.hq_planogram import (
    ShelfCanvas,
    _layout_products,
    block_sales_copy,
    department_row_blocks,
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


def _day(store_id, day, **departments):
    return SimpleNamespace(store_id=store_id, day=day, by_department=dict(departments))


def _state(day, phase, records):
    return SimpleNamespace(day=day, phase=phase, store_days=list(records))


def test_department_week_compare_reads_store_days_and_em_dash_without_prior():
    # Seven closed days, no earlier ledger rows: last week is real, prior is '—'.
    records = [
        _day("evansville", d, grocery=1000 + d * 10, produce=400)
        for d in range(1, 8)
    ]
    state = _state(day=8, phase="day", records=records)
    stats = department_week_compare(state, "evansville", days=7)
    grocery = stats["grocery"]
    assert grocery["sales"] == sum(1000 + d * 10 for d in range(1, 8))
    assert grocery["has_prior"] is False
    assert grocery["prior"] == 0
    assert grocery["delta_pct"] is None
    assert grocery["share"] is not None
    store_total = grocery["store_total"]
    assert store_total == grocery["sales"] + stats["produce"]["sales"]
    assert abs(grocery["share"] - grocery["sales"] / store_total) < 1e-9
    # A different store, or a missing state, must not invent numbers.
    empty = department_week_compare(state, "missing-store", days=7)
    assert empty["grocery"]["sales"] == 0
    assert empty["grocery"]["has_prior"] is False
    assert department_week_compare(None, "evansville")["grocery"]["sales"] == 0
    assert department_week_compare(SimpleNamespace(), "evansville")["grocery"]["sales"] == 0


def test_department_week_compare_prior_week_and_zero_prior_is_em_dash():
    last_week = [_day("evansville", d, grocery=2000, produce=500) for d in range(8, 15)]
    prior_week = [
        _day("evansville", d, grocery=1000 if d < 14 else 1000, produce=0)
        for d in range(1, 8)
    ]
    state = _state(day=14, phase="evening", records=prior_week + last_week)
    stats = department_week_compare(state, "evansville", days=7)
    grocery = stats["grocery"]
    assert grocery["sales"] == 2000 * 7
    assert grocery["prior"] == 1000 * 7
    assert grocery["has_prior"] is True
    assert grocery["delta_pct"] == (grocery["sales"] - grocery["prior"]) / grocery["prior"]
    produce = stats["produce"]
    assert produce["sales"] == 500 * 7
    assert produce["prior"] == 0
    # Prior week exists for the store, but this department had $0 — no invented rate.
    assert produce["delta_pct"] is None
    assert produce["has_prior"] is True


def test_block_sales_copy_keeps_dollars_and_drops_secondary_on_narrow_blocks():
    stat = {
        "sales": 128_400,
        "prior": 120_000,
        "share": 128_400 / 800_000,
        "delta_pct": (128_400 - 120_000) / 120_000,
        "has_prior": True,
        "store_total": 800_000,
    }
    wide_p, wide_s, tip = block_sales_copy(stat, width=180, include_name="Grocery")
    assert wide_p == money_compact(128_400)
    assert "Grocery" in wide_s
    assert "↑" in wide_s
    assert money(128_400) in tip
    assert money(120_000) in tip
    assert "16.1% of store" in tip or "16.0% of store" in tip or "of store" in tip
    mid_p, mid_s, _ = block_sales_copy(stat, width=120, include_name="Grocery")
    assert mid_p == money_compact(128_400)
    assert "Grocery" not in mid_s
    assert mid_s  # share and/or move still present
    narrow_p, narrow_s, narrow_tip = block_sales_copy(stat, width=60, include_name="Grocery")
    assert narrow_p == money_compact(128_400)
    assert narrow_s == ""
    assert money(128_400) in narrow_tip
    none_p, none_s, none_tip = block_sales_copy(
        {
            "sales": 500,
            "prior": 0,
            "share": 1.0,
            "delta_pct": None,
            "has_prior": False,
            "store_total": 500,
        },
        width=180,
        include_name="Toys",
    )
    assert none_p == money_compact(500)
    assert "—" in none_s
    assert "prior week —" in none_tip
    assert "no prior week" in none_tip


def test_planogram_blocks_show_compact_dollars_and_exact_tooltips(tmp_path, monkeypatch):
    app, window = _boot(tmp_path, monkeypatch)
    _advance(window.state, 16, restock=True)
    if hasattr(window, "refresh"):
        window.refresh()
    app.processEvents()
    window._open_app("planograms")
    app.processEvents()
    canvas = window.desktop.planogram.canvas
    canvas.resize(max(canvas.width(), 640), max(canvas.height(), 400))
    app.processEvents()
    # Force a paint so blocks are recorded.
    pix = canvas.grab()
    assert not pix.isNull()
    assert canvas.blocks, "department / aisle blocks should be painted with sales chips"
    # Layout still groups contiguous same-department facings.
    rows = canvas.layout_products
    expected = [block for row in rows for block in department_row_blocks(row)]
    painted_depts = [(b["dept"],) for b in canvas.blocks]
    assert [b[0] for b in expected] == [b["dept"] for b in canvas.blocks]
    store_id = "evansville"
    stats = department_week_compare(window.state, store_id, days=7)
    store_total = next(iter(stats.values()))["store_total"]
    assert store_total > 0, "a 16-day E7 store should have last-week department sales"
    for block in canvas.blocks:
        stat = stats[block["dept"]]
        assert block["primary"] == money_compact(stat["sales"])
        assert block["sales"] == stat["sales"]
        tip = block["tip"]
        assert money(stat["sales"]) in tip
        assert "last week" in tip
        assert "prior week" in tip
        if stat["has_prior"]:
            assert money(stat["prior"]) in tip
        else:
            assert "prior week —" in tip
        if stat["share"] is not None:
            assert "of store" in tip
        # Exact dollars, never a made-up figure.
        assert "$" in tip
    # At 1100x700 the dollars stay; secondary may be dropped on single-facing blocks.
    _resize(window, app, (1100, 700))
    window._open_app("planograms")
    app.processEvents()
    canvas.grab()
    assert canvas.blocks
    for block in canvas.blocks:
        stat = stats[block["dept"]]
        assert block["primary"] == money_compact(stat["sales"]), (
            f"{block['dept']} lost its dollars at 1100x700: {block['primary']!r}"
        )
        assert money(stat["sales"]) in block["tip"]
    window.close()


def test_shelf_canvas_accepts_injected_stats_without_a_game():
    canvas = ShelfCanvas()
    rows = _layout_products("balanced")
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
    canvas.set_layout(rows, stats=stats)
    canvas.resize(800, 480)
    canvas.grab()
    grocery = [b for b in canvas.blocks if b["dept"] == "grocery"]
    assert grocery
    assert grocery[0]["primary"] == money_compact(12_400)
    assert money(12_400) in grocery[0]["tip"]
    assert money(11_000) in grocery[0]["tip"]
    assert grocery[0]["rect"].width() >= 28
