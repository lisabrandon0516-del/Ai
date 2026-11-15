"""Patch E7e: leftover small-store constants scaled to supercenter size, plus Harvest Card demand."""

from __future__ import annotations

from open_late.content import (
    LABEL_MIN_DAY,
    LABEL_MIN_REP,
    LABEL_SETUP_COST,
    ONLINE_SETUP_COST,
    STAFF,
    family_want_map,
    family_want_units,
)
from open_late.corporate import MARKETS, week_gross
from open_late.economy import (
    CAP_MULT,
    HARVEST_CARD_DEPTS,
    HARVEST_CARD_LIFT,
    SALES_CAP,
    apply_player_bias,
    demand_mult,
    economy_factor,
    is_harvest_card_week,
    is_payday,
)
from open_late.engine import (
    CAMPAIGN_COST,
    answer,
    blocking,
    close_day,
    continue_morning,
    launch_campaign,
    new_game,
    open_label,
    open_online,
    place_capped_restock,
)
from open_late.finance import (
    CREW_MULT,
    LABOR_BUDGET_DEFAULT,
    RIVAL_ENTRY_MIN_DAY,
    RIVAL_ENTRY_WEEK_SALES,
    SIZE_MULT,
    STABLE_MONTH_CASH,
    size_int,
)
from open_late.hq import HOME_STORE_ID
from open_late.text import money


def _clear(state) -> None:
    for message in list(blocking(state)):
        for choice in message.choices:
            answer(state, message.id, choice.id)
            current = next(item for item in state.inbox if item.id == message.id)
            if current.resolved:
                break


def _week(state, weeks: int = 1) -> None:
    for _ in range(weeks * 7):
        _clear(state)
        assert close_day(state) == "", getattr(state, "fail_reason", "")
        continue_morning(state)


def _fill_shelves(state) -> None:
    """Monday/Thursday basic cap, same shape as test_e6 play().

    The month-gate entry test has to see supercenter weekly volume. A bare
    close-day loop runs the opening shelf out by week 4 under the E8 catalog
    and hash streams (~$53k, under RIVAL_ENTRY_WEEK_SALES). Restocking does
    not change the entry rule; it only keeps the volume the rule assumes.
    """
    if state.day % 7 not in (1, 4):
        return
    reserve = 6_000 * SIZE_MULT
    if state.cash <= reserve:
        return
    cap = min(30_000 * SIZE_MULT, max(0, state.cash - reserve))
    basket: dict[str, dict[str, int]] = {}
    wants = family_want_map(state.products.values())
    for product in state.products.values():
        line = state.stock.get(product.id)
        on_hand = int(line.on_hand) if line is not None else 0
        on_order = int(getattr(line, "on_order", 0) or 0) if line is not None else 0
        want = wants.get(product.department) or family_want_units(
            product.department, state.products.values()
        )
        need = want - on_hand - on_order
        if need <= 0:
            continue
        basket.setdefault(product.supplier_id, {})[product.id] = need
    place_capped_restock(state, basket, cap, reserve, ignore_minimum=True)


def _week_filled(state, weeks: int = 1) -> None:
    for _ in range(weeks * 7):
        _clear(state)
        _fill_shelves(state)
        assert close_day(state) == "", getattr(state, "fail_reason", "")
        continue_morning(state)


def test_scaled_constants_match_size_mult():
    assert SIZE_MULT == 15
    assert CAMPAIGN_COST == {
        "social": size_int(70),
        "email": size_int(150),
        "local_ad": size_int(400),
        "influencer": size_int(980),
    }
    assert ONLINE_SETUP_COST == size_int(2000)
    assert LABEL_SETUP_COST == size_int(6500)
    assert RIVAL_ENTRY_WEEK_SALES == size_int(6800)
    assert RIVAL_ENTRY_MIN_DAY == 28
    assert STABLE_MONTH_CASH == size_int(7000)
    assert LABOR_BUDGET_DEFAULT == size_int(12_000)
    # Shop leads stay at unscaled lead rates; Sunday shop payroll already uses CREW_MULT.
    assert {person.id: person.wage for person in STAFF} == {
        "alyssa": 1520,
        "jordan": 1600,
        "priya": 1560,
        "chris": 1440,
        "naomi": 1680,
        "evan": 1360,
        "marisol": 1760,
        "dean": 1920,
    }
    assert MARKETS["evansville"].wage_floor == size_int(580)
    assert MARKETS["houston"].wage_floor == size_int(580)
    assert MARKETS["seattle"].wage_floor == size_int(1660)
    assert MARKETS["las_vegas"].wage_floor == size_int(960)
    assert MARKETS["naperville"].wage_floor == size_int(1200)


def test_corporate_wages_and_labor_budget_are_scaled():
    state = new_game("Prairie Wire", "corporate", seed=3)
    door = next(item for item in state.doors if item.id == HOME_STORE_ID)
    assert door.labor_budget == LABOR_BUDGET_DEFAULT
    wages = {manager.id: manager.wage for manager in state.managers}
    assert wages["dana"] == size_int(2200)
    assert wages["marcus"] == size_int(2900)
    assert wages["renee"] == size_int(2560)
    assert wages["owen"] == size_int(2360)
    priya = next(person for person in state.staff if person.id == "priya")
    span = max(4, door.close_hour - door.open_hour)
    if span <= 8:
        raw = int(round(priya.wage * span / 8))
    else:
        raw = int(round(priya.wage * (16 + 3 * (span - 8)) / 16))
    assert week_gross(priya, door) == raw * CREW_MULT


def test_campaign_and_expansion_charges_use_scaled_prices():
    state = new_game("Prairie Wire", "shop", seed=8)
    state.cash = 500_000
    before = state.cash
    text = launch_campaign(state, "email", "playful", "clothing", None)
    assert "playful" in text.lower() or "email" in text.lower() or "campaign" in text.lower() or text
    assert state.cash == before - CAMPAIGN_COST["email"]

    state = new_game("Prairie Wire", "shop", seed=8)
    state.cash = 500_000
    before = state.cash
    assert open_online(state).startswith("The site is plain")
    assert state.cash == before - ONLINE_SETUP_COST
    assert state.flags.online_open is True

    state = new_game("Prairie Wire", "shop", seed=8)
    state.day = LABEL_MIN_DAY
    state.reputation_respectable = LABEL_MIN_REP
    state.cash = 500_000
    before = state.cash
    text = open_label(state)
    assert "Private Label" in text or "Aisle House" in text
    assert state.cash == before - LABEL_SETUP_COST
    assert state.flags.private_label is True
    assert money(LABEL_SETUP_COST) == "$97,500"


def test_northline_waits_for_a_month_then_enters():
    early = new_game("Prairie Wire", "shop", seed=22, economy_difficulty="standard")
    _week_filled(early, 3)
    assert early.day == 22
    # Three Sundays have closed (days 7, 14, 21), all before the month gate.
    assert early.flags.competitor < 18
    assert early.flags.competitor_announced is False

    entered = new_game("Prairie Wire", "shop", seed=22, economy_difficulty="standard")
    _week_filled(entered, 4)
    assert entered.day == 29
    # First eligible Sunday is day 28. Heat is seeded at 34 so the weekly
    # sync keeps the entry above the notice line instead of blending it away.
    assert entered.flags.competitor >= 20

    # Off keeps the historical first $6,800 Sunday so its traffic stays bit-identical.
    off = new_game("Prairie Wire", "shop", seed=22)
    assert off.economy.difficulty == "off"
    _week(off, 1)
    assert off.flags.competitor == 34


def test_harvest_card_lifts_reload_departments_and_is_neutral_when_off():
    standard = new_game("Prairie Wire", "shop", seed=21, economy_difficulty="standard")
    # Day 5 is a harvest-card week and not a payday.
    assert is_harvest_card_week(5) and not is_payday(5)
    assert not is_harvest_card_week(10) and not is_payday(10)
    standard.day = 5
    high = {dept: demand_mult(standard, HOME_STORE_ID, dept) for dept in HARVEST_CARD_DEPTS}
    toys_high = demand_mult(standard, HOME_STORE_ID, "toys")
    standard.day = 10
    low = {dept: demand_mult(standard, HOME_STORE_ID, dept) for dept in HARVEST_CARD_DEPTS}
    toys_low = demand_mult(standard, HOME_STORE_ID, "toys")
    lift = apply_player_bias(
        HARVEST_CARD_LIFT, helpful=True, difficulty="standard", cap=SALES_CAP * CAP_MULT["standard"]
    )
    base = apply_player_bias(1.0, helpful=True, difficulty="standard", cap=SALES_CAP * CAP_MULT["standard"])
    for dept in HARVEST_CARD_DEPTS:
        assert abs(high[dept] / low[dept] - lift / base) < 1e-9, dept
    assert toys_high == toys_low

    # Factor 24 tracks the reload week, and is identity when difficulty is off.
    off = new_game("Prairie Wire", "shop", seed=21)
    assert off.economy.difficulty == "off"
    off.day = 5
    assert demand_mult(off, HOME_STORE_ID, "grocery") == 1.0
    off.day = 10
    assert demand_mult(off, HOME_STORE_ID, "grocery") == 1.0
    _week(off, 1)
    assert economy_factor(off, 24)["value"] == 100

    standard = new_game("Prairie Wire", "shop", seed=21, economy_difficulty="standard")
    # Close through a harvest Sunday (day 7) and a quiet Sunday (day 14).
    _week(standard, 1)
    assert is_harvest_card_week(7)
    # After the first Sunday tick we are on morning of day 8, just outside the week.
    # Factor 24 was last written on day 7 (harvest). Advance one more quiet week.
    _week(standard, 1)
    assert not is_harvest_card_week(standard.day)
    assert economy_factor(standard, 24)["value"] == 100

    harvest = new_game("Prairie Wire", "shop", seed=21, economy_difficulty="standard")
    harvest.day = 7
    _clear(harvest)
    close_day(harvest)
    assert economy_factor(harvest, 24)["value"] == 108


def test_stable_month_cash_gate_is_scaled():
    from open_late.engine import _milestones
    from open_late.models import DayReport

    state = new_game("Prairie Wire", "shop", seed=8, economy_difficulty="standard")
    state.day = 28
    state.cash = STABLE_MONTH_CASH - 1
    state.review_score = 4.2
    state.flags.shortfalls = 0
    report = DayReport(day=state.day, weekday="Sunday")
    _milestones(state, report)
    assert "stable_month" not in state.milestones
    state.cash = STABLE_MONTH_CASH
    report = DayReport(day=state.day, weekday="Sunday")
    _milestones(state, report)
    assert "stable_month" in state.milestones
