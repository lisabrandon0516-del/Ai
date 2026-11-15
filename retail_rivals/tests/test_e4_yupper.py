"""Patch E4: attribution desk, tax fold (104/106), and difficulty survival."""

from __future__ import annotations

from open_late.content import family_want_map, family_want_units, want_units

from open_late.books import tax_on
from open_late.economy import (
    economy_calendar,
    economy_factor,
    economy_factors,
    economy_news,
    economy_snapshot,
    economy_sparklines,
    economy_store_impact,
    economy_tick,
    force_event,
)
from open_late.economy_e3 import factors_in_range
from open_late.economy_e4 import SALES_GRACE, VISIT_BIAS, BILL_GRACE, BILL_DISCOUNT, sales_tax_index, withholding_index
from open_late.engine import (
    _add_order,
    answer,
    blocking,
    close_day,
    continue_morning,
    hire,
    launch_campaign,
    new_game,
    set_assignment,
)
from open_late.finance import SIZE_MULT, pay_advice
from open_late.hq import HOME_STORE_ID, store_pnl
from open_late.models import EconomyState, GameState


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


def _staff_care(state) -> None:
    team = [person for person in state.staff if person.employed]
    if len(team) < 2:
        for person in state.staff:
            if not person.employed:
                hire(state, person.id)
                team.append(person)
            if len(team) >= 2:
                break
    if not team:
        return
    dow = (state.day - 1) % 7
    for i, person in enumerate(team):
        want = "off" if dow == i else "floor"
        if person.assignment != want:
            set_assignment(state, person.id, want)


def _restock(state, reserve: int | None = None, target: int | None = None) -> None:
    """Monday top-up of cheap movers after Sunday bills have already cleared."""
    reserve = 22_000 * SIZE_MULT if reserve is None else reserve
    if state.cash <= reserve:
        return
    basket: dict[str, dict[str, int]] = {}
    wants = None if target is not None else family_want_map(state.products.values())
    for product in state.products.values():
        if int(product.cost) > 80:
            continue
        line = state.stock.get(product.id)
        on_hand = int(line.on_hand) if line is not None else 0
        on_order = int(getattr(line, "on_order", 0) or 0) if line is not None else 0
        if target is None:
            want = wants.get(product.department) or family_want_units(product.department, state.products.values())
        else:
            want = target
        need = want - on_hand - on_order
        if need <= 0:
            continue
        basket.setdefault(product.supplier_id, {})[product.id] = need
    cap = min(80_000 * SIZE_MULT, max(0, state.cash - reserve))
    spent = 0
    for supplier_id, items in sorted(basket.items(), key=lambda kv: sum(state.products[pid].cost * qty for pid, qty in kv[1].items())):
        cost = sum(state.products[pid].cost * qty for pid, qty in items.items())
        if spent + cost > cap or state.cash - cost < reserve:
            continue
        _add_order(state, supplier_id, items, ignore_minimum=True)
        spent += cost


def _play(state, weeks: int, promo: bool) -> None:
    for _ in range(weeks * 7):
        if state.day % 7 == 1:
            _restock(state)
        if promo and state.campaign is None and state.day % 28 == 1 and state.cash >= 3_200 * SIZE_MULT:
            launch_campaign(state, "email", "playful", "clothing", None)
        _staff_care(state)
        _close(state)
        if state.failed:
            return
        continue_morning(state)


def test_snapshot_and_reader_shapes():
    state = new_game("Prairie Wire", "shop", seed=4, economy_difficulty="standard")
    snap = economy_snapshot(state)
    assert set(snap) >= {"week_id", "day", "difficulty", "gauges", "cities", "events_active"}
    assert snap["difficulty"] == "standard"
    for row in snap["gauges"]:
        assert set(row) >= {"id", "name", "value", "delta", "unit", "band"}
        assert row["band"] in {"steady", "watch", "alert"}
    row = economy_factor(state, 104, city_id="evansville")
    assert row["id"] == 104
    assert set(row) >= {"id", "name", "category", "scope", "value", "delta", "range", "driver", "cities"}
    rows = economy_factors(state, category="regulation_taxes")
    assert [item["id"] for item in rows] == list(range(104, 112))
    cal = economy_calendar(state, weeks=8)
    assert len(cal) == 8
    assert set(cal[0]) >= {"week_id", "day_from", "day_to", "labels", "city_weather"}
    feed = economy_news(state, limit=3)
    assert isinstance(feed, list)
    assert len(feed) <= 3


def test_old_save_and_store_pnl_keys():
    state = new_game("Basin Review", "shop", seed=1)
    raw = state.model_dump()
    raw.pop("economy", None)
    loaded = GameState.model_validate(raw)
    assert loaded.economy.difficulty == "off"
    snap = economy_snapshot(loaded)
    assert snap["difficulty"] == "off"
    assert tax_on(250, loaded, HOME_STORE_ID) == tax_on(250)
    pnl = store_pnl(state, HOME_STORE_ID, days=1)
    assert set(pnl) >= {"store_id", "name", "days", "sales", "cogs", "labor", "rent", "freight", "shrink", "card_fees", "pos_fees", "contribution"}


def test_store_impact_multiweek_and_filters():
    off = new_game("Nightcourt", "shop", seed=18)
    impact = economy_store_impact(off, HOME_STORE_ID, days=1)
    assert impact["reasons"] == []
    assert set(impact) == {"store_id", "days", "pnl", "neutral_pnl", "delta", "reasons"}

    state = new_game("Nightcourt", "shop", seed=18, economy_difficulty="standard")
    for _ in range(14):
        _close(state)
        continue_morning(state)
    impact = economy_store_impact(state, HOME_STORE_ID, days=7)
    assert set(impact) == {"store_id", "days", "pnl", "neutral_pnl", "delta", "reasons"}
    by_line: dict[str, int] = {}
    for row in impact["reasons"]:
        assert set(row) >= {"factor_id", "name", "line", "department", "dollars", "note"}
        by_line[row["line"]] = by_line.get(row["line"], 0) + int(row["dollars"])
    for line, total in by_line.items():
        assert total == impact["delta"][line]
    # Filters keep the same shape and only the requested slice.
    tight = economy_store_impact(state, HOME_STORE_ID, days=7, min_dollars=10_000_000)
    assert tight["reasons"] == []
    ev = economy_store_impact(state, HOME_STORE_ID, days=7, events_only=True)
    assert set(ev) == set(impact)
    grocery = economy_store_impact(state, HOME_STORE_ID, days=7, department="grocery", category="commodity_prices")
    assert set(grocery) == set(impact)
    for row in grocery["reasons"]:
        assert row["department"] in (None, "grocery")


def test_sparklines_pnl_and_chain_overlay():
    state = new_game("Lakeshore Notice", "shop", seed=9, economy_difficulty="standard")
    for _ in range(14):
        _close(state)
        continue_morning(state)
    sparks = economy_sparklines(state, [1, 2, 6], weeks=12)
    assert set(sparks) == {"weeks", "series"}
    assert "1" in sparks["series"]
    assert len(sparks["series"]["1"]) == len(sparks["weeks"])
    lined = economy_sparklines(state, [1], weeks=12, store_id=HOME_STORE_ID, lines=["sales", "contribution"])
    assert "sales" in lined["series"]
    assert "chain:sales" in lined["series"]
    assert "chain:contribution" in lined["series"]
    assert len(lined["series"]["sales"]) == len(lined["weeks"])


def test_tax_fold_104_and_106():
    off = new_game("Riverbend Desk", "shop", seed=6)
    live = new_game("Riverbend Desk", "shop", seed=6, economy_difficulty="standard")
    person = next(item for item in off.staff if item.employed)
    # Off and a 100-index live shop stay bit-identical.
    assert tax_on(2500, off, HOME_STORE_ID) == tax_on(2500)
    assert tax_on(2500, live, HOME_STORE_ID) == tax_on(2500)
    assert pay_advice(off, person).state_tax == pay_advice(live, person).state_tax
    # 104 lifts the sales-tax dollar.
    live.economy.values["104:evansville"] = 108
    assert tax_on(10_000, live, HOME_STORE_ID) > tax_on(10_000, off, HOME_STORE_ID)
    assert sales_tax_index(live, HOME_STORE_ID) == 108
    # 106 lifts Evansville withholding; a zero-rate city stays 0.
    live.economy.values["106:evansville"] = 110
    assert pay_advice(live, person).state_tax > pay_advice(off, person).state_tax
    assert withholding_index(live, "houston") == 100
    live.economy.values["106:houston"] = 110
    assert withholding_index(live, "houston") == 100


def test_stern_params_unchanged():
    from open_late.economy import CAP_MULT, EVENT_P_MULT, SIGMA_MULT

    assert SIGMA_MULT["stern"] == 1.35 and EVENT_P_MULT["stern"] == 1.35
    assert CAP_MULT["stern"] == 1.0
    assert SALES_GRACE["stern"] == 0.0 and VISIT_BIAS["stern"] == 0
    assert BILL_GRACE["stern"] == 0.0 and BILL_DISCOUNT["stern"] == 0.0
    assert SALES_GRACE["off"] == 0.0 and VISIT_BIAS["off"] == 0


def test_calm_passive_survives_26_weeks():
    seed = 22
    state = new_game("Harbor Ledger", "shop", seed=seed, economy_difficulty="calm")
    _play(state, 26, promo=False)
    assert not state.failed, state.fail_reason
    assert state.cash > 0
    assert factors_in_range(state) == []


def test_standard_moderate_survives_26_weeks():
    seed = 22
    state = new_game("Harbor Ledger", "shop", seed=seed, economy_difficulty="standard")
    _play(state, 26, promo=True)
    assert not state.failed, state.fail_reason
    assert state.cash > 0
    assert factors_in_range(state) == []


def test_stern_26_weeks_stays_in_range():
    seed = 22
    state = new_game("Harbor Ledger", "shop", seed=seed, economy_difficulty="stern")
    for _ in range(26):
        if state.day % 7 != 0:
            state.day += 7 - (state.day % 7)
        economy_tick(state)
        state.day += 7
    assert factors_in_range(state) == []
