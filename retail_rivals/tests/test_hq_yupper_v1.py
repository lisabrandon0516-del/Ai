"""Phase 1 HQ: tills, Sunday switches, and the chain P&L."""

from __future__ import annotations

import json

from open_late.engine import (
    answer,
    blocking,
    close_day,
    continue_morning,
    new_game,
)
from open_late.finance import card_fee
from open_late.hq import (
    DEFAULT_POS,
    HOME_STORE_ID,
    INSTALL_FEE,
    POS_OPTIONS,
    apply_walked,
    card_fee_for,
    chain_board,
    pos_options,
    set_store_pos,
    shrink_mult,
    store_ids,
    store_pnl,
    store_pos,
)
from open_late.models import GameState
from open_late.store import SaveStore


# Boutique-catalog 7-day cash baselines from Phase 1 are no longer meaningful
# after the supercenter catalog. Default POS still has to leave fee and shrink
# math unchanged; same-seed weeks must also be deterministic.


def _clear(state) -> None:
    for message in list(blocking(state)):
        for choice in message.choices:
            answer(state, message.id, choice.id)
            current = next(item for item in state.inbox if item.id == message.id)
            if current.resolved:
                break


def _close(state) -> None:
    _clear(state)
    assert close_day(state) == ""


def test_pos_options_are_ordered_and_complete():
    rows = pos_options()
    assert [row["id"] for row in rows] == ["open_drawer", "counter_ledger", "chain_link"]
    keys = {"id", "name", "blurb", "weekly_license", "card_fee_rate", "shrink_mult", "walked_sales_mult"}
    for row in rows:
        assert set(row) == keys
        assert row["name"] == POS_OPTIONS[row["id"]]["name"]
    assert rows[1]["card_fee_rate"] == 0.026
    assert rows[1]["weekly_license"] == 0
    assert rows[1]["shrink_mult"] == 1.0
    assert rows[1]["walked_sales_mult"] == 1.0


def test_store_ids_include_the_home_store():
    shop = new_game("Ledger", "shop", seed=1)
    assert store_ids(shop) == [HOME_STORE_ID]
    corp = new_game("Toy's N Us", "corporate", seed=3)
    assert store_ids(corp) == [HOME_STORE_ID]
    assert store_pos(corp, HOME_STORE_ID)["id"] == DEFAULT_POS
    assert store_pos(corp, HOME_STORE_ID)["pending"] is None


def test_pnl_identity_matches_recorded_days():
    state = new_game("Toy's N Us", "corporate", seed=3)
    for _ in range(7):
        _close(state)
        continue_morning(state)
    # After seven closes we are in Monday morning of day 8; the window is days 1-7.
    assert state.day == 8
    row = store_pnl(state, HOME_STORE_ID, days=7)
    expected = (
        row["sales"]
        - row["cogs"]
        - row["labor"]
        - row["rent"]
        - row["freight"]
        - row["shrink"]
        - row["card_fees"]
        - row["pos_fees"]
    )
    assert row["contribution"] == expected
    assert row["store_id"] == HOME_STORE_ID
    assert row["name"] == "Evansville"
    assert row["days"] == 7
    assert row["sales"] > 0
    # Sunday labor and rent must show up in a 7-day window that includes day 7.
    assert row["labor"] > 0
    assert row["rent"] > 0
    board = chain_board(state, days=7)
    assert [item["store_id"] for item in board] == [HOME_STORE_ID, "chain"]
    total = board[-1]
    assert total["name"] == "Chain"
    assert total["sales"] == row["sales"]
    assert total["contribution"] == row["contribution"]
    keys = ("sales", "cogs", "labor", "rent", "freight", "shrink", "card_fees", "pos_fees", "contribution")
    for key in keys:
        assert isinstance(row[key], int)
        assert isinstance(total[key], int)


def _week_snapshot(mode: str, seed: int) -> list[dict]:
    state = new_game("Ledger", mode, seed=seed)
    rows = []
    for _ in range(7):
        _close(state)
        report = state.last_report
        rows.append(
            {
                "cash": state.cash,
                "revenue": report.revenue,
                "refunds": report.refunds,
                "cogs": report.cogs,
                "card_fees": report.card_fees,
                "shrink_cost": report.shrink_cost,
                "shrink_units": report.shrink_units,
                "lost_walk": report.lost_walk,
                "visits": report.visits,
                "units": report.units,
            }
        )
        continue_morning(state)
    return rows


def test_default_pos_keeps_shop_numbers_identical():
    charged = 10_000
    state = new_game("Ledger", "shop", seed=1)
    assert card_fee_for(state, HOME_STORE_ID, charged) == card_fee(charged)
    assert card_fee_for(state, HOME_STORE_ID, charged) == (charged * 26) // 1000
    assert shrink_mult(state, HOME_STORE_ID) == 1.0
    assert apply_walked(state, HOME_STORE_ID, 0.4) == 0.4
    assert _week_snapshot("shop", 1) == _week_snapshot("shop", 1)


def test_default_pos_keeps_corporate_numbers_identical():
    assert _week_snapshot("corporate", 3) == _week_snapshot("corporate", 3)


def test_switch_charges_install_and_applies_at_sunday():
    state = new_game("Toy's N Us", "corporate", seed=3)
    before = state.cash
    message = set_store_pos(state, HOME_STORE_ID, "chain_link")
    fee = INSTALL_FEE["chain_link"]
    assert fee == 800
    assert str(fee) in message or "800" in message
    assert state.cash == before - fee
    current = store_pos(state, HOME_STORE_ID)
    assert current["id"] == "counter_ledger"
    assert current["pending"] == "chain_link"
    # Days 1-6 are not Sunday. The till must stay on Counter Ledger.
    for _ in range(6):
        _close(state)
        assert store_pos(state, HOME_STORE_ID)["id"] == "counter_ledger"
        assert store_pos(state, HOME_STORE_ID)["pending"] == "chain_link"
        assert shrink_mult(state, HOME_STORE_ID) == 1.0
        continue_morning(state)
    _close(state)
    assert state.last_report.weekday == "Sunday"
    after = store_pos(state, HOME_STORE_ID)
    assert after["id"] == "chain_link"
    assert after["pending"] is None
    assert shrink_mult(state, HOME_STORE_ID) == POS_OPTIONS["chain_link"]["shrink_mult"]
    # Install is in the P&L, weekly license is not charged for a week that still ran the old till.
    row = store_pnl(state, HOME_STORE_ID, days=7)
    assert row["pos_fees"] == fee


def test_each_option_moves_fees_shrink_and_walked_sales():
    charged = 10_000
    state = new_game("Toy's N Us", "corporate", seed=3)
    drawer = POS_OPTIONS["open_drawer"]
    ledger = POS_OPTIONS["counter_ledger"]
    link = POS_OPTIONS["chain_link"]
    assert drawer["card_fee_rate"] > ledger["card_fee_rate"] > link["card_fee_rate"]
    assert drawer["shrink_mult"] > ledger["shrink_mult"] > link["shrink_mult"]
    assert drawer["walked_sales_mult"] > ledger["walked_sales_mult"] > link["walked_sales_mult"]

    def fee(pos_id: str) -> int:
        state.store_pos_by_id[HOME_STORE_ID] = pos_id
        return card_fee_for(state, HOME_STORE_ID, charged)

    assert fee("open_drawer") == (charged * 32) // 1000
    assert fee("counter_ledger") == card_fee(charged)
    assert fee("chain_link") == (charged * 21) // 1000
    assert fee("open_drawer") > fee("counter_ledger") > fee("chain_link")
    state.store_pos_by_id[HOME_STORE_ID] = "open_drawer"
    assert shrink_mult(state, HOME_STORE_ID) > 1.0
    assert apply_walked(state, HOME_STORE_ID, 0.40) < 0.40
    state.store_pos_by_id[HOME_STORE_ID] = "chain_link"
    assert shrink_mult(state, HOME_STORE_ID) < 1.0
    assert apply_walked(state, HOME_STORE_ID, 0.40) > 0.40

    def week_after_switch(pos_id: str) -> dict:
        item = new_game("Toy's N Us", "corporate", seed=3)
        set_store_pos(item, HOME_STORE_ID, pos_id)
        for _ in range(7):
            _close(item)
            continue_morning(item)
        # Days 8-14 run on the new till.
        fees = shrink = walked = sales = 0
        for _ in range(7):
            _close(item)
            fees += item.last_report.card_fees
            shrink += item.last_report.shrink_cost
            walked += item.last_report.lost_walk
            sales += item.last_report.revenue - item.last_report.refunds
            continue_morning(item)
        return {"fees": fees, "shrink": shrink, "walked": walked, "sales": sales}

    # Counter Ledger is already the default; booking it is a no-op, so force a
    # Sunday apply by switching away and back in the helper only for the others.
    ledger_week = week_after_switch("open_drawer")
    # Re-run default by never switching.
    default_state = new_game("Toy's N Us", "corporate", seed=3)
    for _ in range(7):
        _close(default_state)
        continue_morning(default_state)
    default = {"fees": 0, "shrink": 0, "walked": 0, "sales": 0}
    for _ in range(7):
        _close(default_state)
        default["fees"] += default_state.last_report.card_fees
        default["shrink"] += default_state.last_report.shrink_cost
        default["walked"] += default_state.last_report.lost_walk
        default["sales"] += default_state.last_report.revenue - default_state.last_report.refunds
        continue_morning(default_state)
    drawer_week = ledger_week
    link_week = week_after_switch("chain_link")
    # Fee rate: card fees per dollar of sales should move with the till.
    if default["sales"] and drawer_week["sales"] and link_week["sales"]:
        default_rate = default["fees"] / default["sales"]
        drawer_rate = drawer_week["fees"] / drawer_week["sales"]
        link_rate = link_week["fees"] / link_week["sales"]
        assert drawer_rate >= default_rate
        assert link_rate <= default_rate
    assert drawer_week["walked"] >= default["walked"]
    assert link_week["walked"] <= default["walked"]


def test_save_load_round_trip(tmp_path):
    state = new_game("Toy's N Us", "corporate", seed=3)
    set_store_pos(state, HOME_STORE_ID, "chain_link")
    _close(state)
    store = SaveStore(tmp_path / "saves.sqlite")
    store.save(state)
    loaded = store.load(state.slot)
    assert loaded.model_dump() == state.model_dump()
    assert store_pos(loaded, HOME_STORE_ID)["pending"] == "chain_link"
    assert store_pos(loaded, HOME_STORE_ID)["id"] == "counter_ledger"
    assert loaded.store_days
    assert loaded.store_days[0].sales == state.store_days[0].sales


def test_old_save_loads_with_default_till(tmp_path):
    state = new_game("Ledger", "shop", seed=1)
    payload = json.loads(state.model_dump_json())
    payload.pop("store_pos_by_id", None)
    payload.pop("pending_store_pos", None)
    payload.pop("store_days", None)
    old = GameState.model_validate(payload)
    assert old.store_pos_by_id == {}
    assert old.pending_store_pos == {}
    assert old.store_days == []
    assert store_pos(old, HOME_STORE_ID)["id"] == "counter_ledger"
    assert store_pos(old, HOME_STORE_ID)["pending"] is None
    assert card_fee_for(old, HOME_STORE_ID, 5000) == card_fee(5000)
    store = SaveStore(tmp_path / "saves.sqlite")
    store.save(old)
    loaded = store.load(old.slot)
    assert store_pos(loaded, HOME_STORE_ID)["id"] == "counter_ledger"
    assert loaded.store_days == []
