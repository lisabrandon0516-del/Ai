"""Patch E1: weekly economy tick, week card, difficulty, and apply hooks."""

from __future__ import annotations

from open_late.departments import DEPARTMENT_IDS
from open_late.economy import (
    COMMODITY,
    E1_IDS,
    adjust_freight,
    demand_mult,
    economy_calendar,
    economy_factor,
    economy_factors,
    economy_news,
    economy_snapshot,
    economy_sparklines,
    economy_store_impact,
    economy_tick,
    freight_mult,
    is_harvest_card_week,
    is_payday,
    landed_cost,
    set_economy_difficulty,
    visits_mult,
    week_id,
)
from open_late.engine import (
    Rng,
    answer,
    blocking,
    close_day,
    continue_morning,
    new_game,
    place_order,
)
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


def _week(state, days: int = 7) -> None:
    for _ in range(days):
        _close(state)
        continue_morning(state)


def test_old_save_loads_neutral():
    state = new_game("Prairie Goods", "shop", seed=11)
    raw = state.model_dump()
    raw.pop("economy", None)
    loaded = GameState.model_validate(raw)
    assert loaded.economy.difficulty == "off"
    assert loaded.economy.values == {}
    _week(loaded, 3)
    assert loaded.economy.difficulty == "off"
    # Week-card apply stays an identity while off.
    assert visits_mult(loaded, HOME_STORE_ID) == 1.0
    assert demand_mult(loaded, HOME_STORE_ID, "grocery") == 1.0
    assert freight_mult(loaded, HOME_STORE_ID) == 1.0


def test_new_game_defaults_to_off():
    shop = new_game("Harbor Mart", "shop", seed=4)
    assert shop.economy.difficulty == "off"
    corp = new_game("Basin Supercenter", "corporate", seed=4)
    assert corp.economy.difficulty == "off"
    live = new_game("Lakeshore Desk", "shop", seed=4, economy_difficulty="standard")
    assert live.economy.difficulty == "standard"
    # First week is still a 100 card.
    assert live.economy.visits[HOME_STORE_ID] == 100
    assert live.economy.cost[HOME_STORE_ID]["grocery"] == 100


def test_same_seed_and_week_are_deterministic():
    cards = []
    for _ in range(2):
        state = new_game("Nightcourt Market", "shop", seed=42, economy_difficulty="standard")
        _week(state, 14)
        cards.append(
            (
                dict(state.economy.values),
                dict(state.economy.visits),
                {k: dict(v) for k, v in state.economy.cost.items()},
                dict(state.economy.freight),
            )
        )
    assert cards[0] == cards[1]


def test_economy_tick_does_not_consume_sale_rng():
    live = new_game("Riverbend Desk", "shop", seed=7, economy_difficulty="standard")
    _week(live, 7)
    counter = live.rng_counter
    economy_tick(live)
    assert live.rng_counter == counter
    # A frozen sale-RNG sequence is unchanged by ticking.
    probe = new_game("Riverbend Desk", "shop", seed=7, economy_difficulty="stern")
    rng = Rng(probe)
    first = [rng.uniform(0.0, 1.0) for _ in range(8)]
    snapshot = probe.rng_counter
    economy_tick(probe)
    assert probe.rng_counter == snapshot
    probe.rng_counter = 0
    rng2 = Rng(probe)
    second = [rng2.uniform(0.0, 1.0) for _ in range(8)]
    assert first == second


def test_commodities_move_cogs_and_leave_list_cost():
    state = new_game("Prairie Wire Mart", "shop", seed=15, economy_difficulty="standard")
    state.economy.last_week_id = 0
    grocery = next(p for p in state.products.values() if p.department == "grocery")
    list_cost = grocery.cost
    state.economy.cost[HOME_STORE_ID] = {dept: 100 for dept in DEPARTMENT_IDS}
    state.economy.cost[HOME_STORE_ID]["grocery"] = 115
    billed = landed_cost(state, HOME_STORE_ID, "grocery", list_cost * 10)
    from open_late.economy import CAP_MULT, COGS_CAP, apply_player_bias

    expected = int(round(list_cost * 10 * apply_player_bias(1.15, helpful=False, difficulty="standard", cap=COGS_CAP * CAP_MULT["standard"])))
    assert billed == expected
    assert grocery.cost == list_cost
    # Off stays at list cost.
    off = new_game("Prairie Wire Mart", "shop", seed=15)
    assert landed_cost(off, HOME_STORE_ID, "grocery", list_cost * 10) == list_cost * 10


def test_payday_lifts_grocery_sales():
    state = new_game("Harvest Lane", "shop", seed=21, economy_difficulty="standard")
    # Payday days 1-2 and 15-16; harvest-card week is days 1-7. Use 15 vs 17
    # so the payday hook is measured without the Harvest Card stack.
    assert is_payday(1) and is_payday(2) and is_payday(15)
    assert not is_payday(3) and not is_payday(17)
    assert is_harvest_card_week(1) and not is_harvest_card_week(15)
    assert not is_harvest_card_week(17)
    state.day = 15
    grocery_pay = demand_mult(state, HOME_STORE_ID, "grocery")
    toys_pay = demand_mult(state, HOME_STORE_ID, "toys")
    state.day = 17
    grocery_quiet = demand_mult(state, HOME_STORE_ID, "grocery")
    from open_late.economy import CAP_MULT, SALES_CAP, apply_player_bias

    pay = apply_player_bias(1.08, helpful=True, difficulty="standard", cap=SALES_CAP * CAP_MULT["standard"])
    base = apply_player_bias(1.0, helpful=True, difficulty="standard", cap=SALES_CAP * CAP_MULT["standard"])
    assert abs(grocery_pay / grocery_quiet - pay / base) < 1e-9
    assert toys_pay == demand_mult(state, HOME_STORE_ID, "toys")
    for dept in ("household", "meat_dairy", "produce"):
        state.day = 15
        high = demand_mult(state, HOME_STORE_ID, dept)
        state.day = 17
        low = demand_mult(state, HOME_STORE_ID, dept)
        assert abs(high / low - pay / base) < 1e-9
    # Factor 24 is a calendar index; writing it still does not move demand.
    # The Harvest Card demand hook is covered in test_e7e_yupper.
    _week(state, 7)
    assert not is_harvest_card_week(state.day)
    assert economy_factor(state, 24)["value"] == 100
    from open_late.economy import _bake_card

    _bake_card(state, week_id(state.day))
    before = {
        dept: demand_mult(state, HOME_STORE_ID, dept) for dept in DEPARTMENT_IDS
    }
    state.economy.values["24"] = 200
    _bake_card(state, week_id(state.day))
    after = {
        dept: demand_mult(state, HOME_STORE_ID, dept) for dept in DEPARTMENT_IDS
    }
    assert after == before
    labels = [label for row in economy_calendar(state, weeks=8) for label in row["labels"]]
    assert "Harvest Card" in labels
    assert "Payday" in labels


def test_caps_hold_after_stacking():
    state = new_game("Stern Caps", "shop", seed=9, economy_difficulty="stern")
    state.economy.last_week_id = 3
    for fid in range(1, 11):
        state.economy.values[str(fid)] = 180
    for fid in (11, 21):
        state.economy.values[f"{fid}:evansville"] = 180
    for fid in COMMODITY:
        state.economy.values[str(fid)] = 180
    from open_late.economy import _bake_card

    _bake_card(state, 3)
    visit = visits_mult(state, HOME_STORE_ID)
    demands = [demand_mult(state, HOME_STORE_ID, dept) for dept in DEPARTMENT_IDS]
    # Payday may still apply on day 1; strip it by moving off payday.
    state.day = 3
    demands = [demand_mult(state, HOME_STORE_ID, dept) for dept in DEPARTMENT_IDS]
    visit = visits_mult(state, HOME_STORE_ID)
    product = visit * (sum(demands) / len(demands))
    assert product <= 1.2200001
    assert product >= 0.78
    for dept in DEPARTMENT_IDS:
        assert 0.85 <= (state.economy.cost[HOME_STORE_ID][dept] / 100) <= 1.15
    assert 0.75 <= freight_mult(state, HOME_STORE_ID) <= 1.25
    # Calm uses 75% of the caps.
    calm = new_game("Calm Caps", "shop", seed=9, economy_difficulty="calm")
    calm.economy.values = dict(state.economy.values)
    calm.economy.last_week_id = 3
    calm.day = 3
    _bake_card(calm, 3)
    c_visit = visits_mult(calm, HOME_STORE_ID)
    c_demands = [demand_mult(calm, HOME_STORE_ID, dept) for dept in DEPARTMENT_IDS]
    c_product = c_visit * (sum(c_demands) / len(c_demands))
    assert c_product <= 1.0 + 0.22 * 0.75 + 1e-6
    # Caps are stored as integer indexes, so 75% of 15%/25% rounds to 111 / 119.
    assert 0.89 - 1e-9 <= calm.economy.cost[HOME_STORE_ID]["grocery"] / 100 <= 1.11 + 1e-9
    assert 0.81 - 1e-9 <= freight_mult(calm, HOME_STORE_ID) <= 1.19 + 1e-9


def test_store_pnl_still_balances_with_economy_on():
    state = new_game("Contribution Check", "corporate", seed=3, economy_difficulty="standard")
    _week(state, 14)
    pnl = store_pnl(state, HOME_STORE_ID, days=14)
    contribution = (
        pnl["sales"]
        - pnl["cogs"]
        - pnl["labor"]
        - pnl["rent"]
        - pnl["freight"]
        - pnl["shrink"]
        - pnl["card_fees"]
        - pnl["pos_fees"]
    )
    assert pnl["contribution"] == contribution


def test_difficulty_sunday_switch_and_api_shapes():
    state = new_game("Switchboard", "shop", seed=18)
    assert state.economy.difficulty == "off"
    message = set_economy_difficulty(state, "Stern")
    assert "Stern" in message
    assert state.economy.difficulty == "off"
    assert state.economy.pending_difficulty == "stern"
    _week(state, 7)
    assert state.economy.difficulty == "stern"
    assert state.economy.pending_difficulty == ""
    # After the Sunday that applied Stern, the next week's card may leave 100.
    assert state.economy.last_week_id >= 0

    snap = economy_snapshot(state)
    assert snap["difficulty"] == "stern"
    assert set(snap) >= {"week_id", "day", "difficulty", "gauges", "cities", "events_active"}
    assert isinstance(snap["events_active"], list)
    for event in snap["events_active"]:
        assert set(event) >= {"factor_id", "name", "city_id", "store_ids", "day_start", "day_end", "severity"}
    assert [row["id"] for row in snap["gauges"]] == [1, 2, 4, 6, 7]
    for row in snap["gauges"]:
        assert set(row) >= {"id", "name", "value", "delta", "unit"}
    assert {row["city_id"] for row in snap["cities"]} == {
        "evansville",
        "seattle",
        "houston",
        "las_vegas",
        "naperville",
    }
    for row in snap["cities"]:
        assert set(row) >= {"city_id", "traffic", "wage_pressure", "weather"}

    row = economy_factor(state, 6)
    assert row["id"] == 6
    assert set(row) >= {"id", "name", "category", "scope", "value", "delta", "range", "driver", "cities"}
    local = economy_factor(state, 11, city_id="seattle")
    assert local["cities"]["seattle"] == local["value"] or "seattle" in local["cities"]

    rows = economy_factors(state)
    assert [item["id"] for item in rows] == list(range(1, 121))
    assert {item["id"] for item in rows if item["id"] in E1_IDS}

    sparks = economy_sparklines(state, [1, 2, 6], weeks=12)
    assert set(sparks) == {"weeks", "series"}
    assert "1" in sparks["series"]

    impact = economy_store_impact(state, HOME_STORE_ID, days=7)
    assert set(impact) == {"store_id", "days", "pnl", "neutral_pnl", "delta", "reasons"}
    assert impact["reasons"] == []
    assert impact["pnl"]["contribution"] == (
        impact["pnl"]["sales"]
        - impact["pnl"]["cogs"]
        - impact["pnl"]["labor"]
        - impact["pnl"]["rent"]
        - impact["pnl"]["freight"]
        - impact["pnl"]["shrink"]
        - impact["pnl"]["card_fees"]
        - impact["pnl"]["pos_fees"]
    )

    news = economy_news(state)
    assert isinstance(news, list)
    for item in news:
        assert set(item) >= {"id", "day", "outlet", "headline", "body", "factor_ids", "store_ids", "severity", "prompt"}
    cal = economy_calendar(state, weeks=8)
    assert len(cal) == 8
    for item in cal:
        assert set(item) >= {"week_id", "day_from", "day_to", "labels", "city_weather"}


def test_off_week_matches_default_new_game():
    a = new_game("Identity Lane", "shop", seed=5)
    b = new_game("Identity Lane", "shop", seed=5, economy_difficulty="off")
    _week(a, 7)
    _week(b, 7)
    assert a.cash == b.cash
    assert a.rng_counter == b.rng_counter
    assert [item.revenue for item in a.history] == [item.revenue for item in b.history]
    assert [item.cogs for item in a.history] == [item.cogs for item in b.history]


def test_place_order_uses_landed_cost_when_live():
    live = new_game("Freight House", "shop", seed=8, economy_difficulty="standard")
    off = new_game("Freight House", "shop", seed=8)
    live.economy.last_week_id = 1
    live.economy.cost[HOME_STORE_ID] = {dept: 100 for dept in DEPARTMENT_IDS}
    live.economy.cost[HOME_STORE_ID]["household"] = 115
    live.economy.freight[HOME_STORE_ID] = 120
    product = live.products["house-dish"]
    before_live = live.cash
    before_off = off.cash
    before_cost = product.cost
    # 3750 units clears Soapstone's $15,000 minimum (list cost $15,000).
    place_order(live, product.supplier_id, {product.id: 3750})
    place_order(off, product.supplier_id, {product.id: 3750})
    spent_live = before_live - live.cash
    spent_off = before_off - off.cash
    assert spent_live > spent_off
    assert product.cost == before_cost
    # Freight hook is an identity when off.
    assert adjust_freight(off, HOME_STORE_ID, 40) == 40
    from open_late.economy import CAP_MULT, FREIGHT_CAP, apply_player_bias

    expected_freight = int(round(40 * apply_player_bias(1.20, helpful=False, difficulty="standard", cap=FREIGHT_CAP * CAP_MULT["standard"])))
    assert adjust_freight(live, HOME_STORE_ID, 40) == expected_freight
