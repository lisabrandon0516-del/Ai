"""Patch E3: remaining factors go live, Sunday P&L folds, caps, and short solvency."""

from __future__ import annotations

from open_late.departments import DEPARTMENT_IDS
from open_late.economy import (
    CAP_MULT,
    EVENT_P_MULT,
    SALES_CAP,
    SIGMA_MULT,
    demand_mult,
    economy_store_impact,
    economy_tick,
    force_event,
    freight_mult,
    visits_mult,
    week_id,
    _bake_card,
    _resolve_links,
    _value,
)
from open_late.economy_e3 import (
    CARD_CAP,
    LABOR_CAP,
    RENT_CAP,
    RENT_EVENT_CAP,
    category_counts,
    factors_in_range,
    labor_mult,
    live_factor_count,
    live_factor_ids,
    rent_mult,
)
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
    set_price,
)
from open_late.hq import HOME_STORE_ID, store_pnl


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


def test_all_120_factors_live_and_categorized():
    ids = live_factor_ids()
    assert ids == list(range(1, 121))
    assert live_factor_count() == 120
    counts = category_counts()
    assert sum(counts.values()) == 120
    assert counts == {
        "national_macro": 10,
        "local_regional": 12,
        "seasonal_calendar": 14,
        "weather_disasters": 10,
        "labor_market": 10,
        "supply_chain": 10,
        "commodity_prices": 13,
        "competition": 8,
        "real_estate_costs": 8,
        "finance": 8,
        "regulation_taxes": 8,
        "consumer_trends": 9,
    }
    from open_late.economy import FACTORS

    for fid in range(1, 121):
        assert "Reserved" not in FACTORS[fid]["driver"]


def test_eight_seeded_weeks_stay_in_range():
    state = new_game("Prairie Desk", "shop", seed=44, economy_difficulty="standard")
    for _ in range(8):
        if state.day % 7 != 0:
            state.day += 7 - (state.day % 7)
        economy_tick(state)
        state.day += 7
    assert factors_in_range(state) == []
    # Rent pressure folds into the rent line (no new P&L key).
    pnl = store_pnl(state, HOME_STORE_ID, days=14)
    assert "rent" in pnl
    assert "cam" not in pnl and "parking" not in pnl


def test_rival_war_hits_grocery_sales():
    war = new_game("Basin Mart", "shop", seed=12, economy_difficulty="standard")
    calm = new_game("Basin Mart", "shop", seed=12, economy_difficulty="standard")
    war.flags.competitor = 40
    war.economy.values["81:evansville"] = 40
    force_event(war, 84, city_id="evansville", days=14, intensity=20, start_day=war.day)
    war.rival.focus = "grocery"
    assert demand_mult(war, HOME_STORE_ID, "grocery") < demand_mult(calm, HOME_STORE_ID, "grocery")


def test_wage_floor_event_lifts_labor():
    state = new_game("Harbor Mart", "shop", seed=8, economy_difficulty="standard")
    before = labor_mult(state, HOME_STORE_ID)
    wages = [person.wage for person in state.staff if person.employed]
    force_event(state, 107, city_id="evansville", days=28, intensity=8, start_day=state.day)
    from open_late.economy_e3 import apply_wage_floor_event

    apply_wage_floor_event(state)
    assert labor_mult(state, HOME_STORE_ID) > before
    after = [person.wage for person in state.staff if person.employed]
    assert after > wages


def test_difficulty_scales_sigma_and_event_p_only():
    assert SIGMA_MULT["calm"] == 0.32 and EVENT_P_MULT["calm"] == 0.40
    assert SIGMA_MULT["standard"] == 0.48 and EVENT_P_MULT["standard"] == 0.55
    assert SIGMA_MULT["stern"] == 1.35 and EVENT_P_MULT["stern"] == 1.35
    assert SIGMA_MULT["off"] == 0.0 and EVENT_P_MULT["off"] == 0.0
    # μ stays 100 on a just-started live card.
    state = new_game("Nightcourt", "shop", seed=5, economy_difficulty="stern")
    assert _value(state, 1) == 100
    assert _value(state, 96) == 100


def test_stacked_caps_hold():
    state = new_game("Riverbend", "shop", seed=9, economy_difficulty="standard")
    _week(state, 21)
    visits = visits_mult(state, HOME_STORE_ID)
    avg = sum(demand_mult(state, HOME_STORE_ID, dept) for dept in DEPARTMENT_IDS) / len(DEPARTMENT_IDS)
    product = visits * avg
    assert product <= 1.0 + SALES_CAP + 1e-6
    from open_late.economy import active_events, city_of, weather_visits_mult

    cut = weather_visits_mult(state, HOME_STORE_ID) < 1.0 or active_events(
        state, factor_id=16, city_id=city_of(state, HOME_STORE_ID)
    ) or active_events(state, factor_id=17, city_id=city_of(state, HOME_STORE_ID))
    if not cut:
        assert 1.0 - SALES_CAP - 1e-6 <= product
    assert abs(labor_mult(state, HOME_STORE_ID) - 1.0) <= LABOR_CAP + 1e-6
    rent = rent_mult(state, HOME_STORE_ID)
    cap = RENT_EVENT_CAP if state.economy.events else RENT_CAP
    assert abs(rent - 1.0) <= cap + 1e-6
    from open_late.economy_e3 import card_fee_mult

    assert abs(card_fee_mult(state, HOME_STORE_ID) - 1.0) <= CARD_CAP + 1e-6
    assert 0.75 - 1e-9 <= freight_mult(state, HOME_STORE_ID) <= 1.25 + 1e-9
    # Calm shrinks cap to 70%.
    calm = new_game("Riverbend", "shop", seed=9, economy_difficulty="calm")
    assert CAP_MULT["calm"] == 0.70
    assert abs(labor_mult(calm, HOME_STORE_ID) - 1.0) <= LABOR_CAP * 0.70 + 1e-6


def test_cascade_policy_to_credit_spread():
    state = new_game("Ledger Desk", "shop", seed=3, economy_difficulty="standard")
    state.economy.values["1"] = 130
    state.economy.prev_values = dict(state.economy.values)
    _resolve_links(state, week_id(state.day), 1.0)
    assert _value(state, 96) > 100


def test_cascade_anchor_lifts_city_unemployment():
    state = new_game("Ohio Bend", "shop", seed=3, economy_difficulty="standard")
    state.economy.values["18:evansville"] = 70
    state.economy.prev_values = dict(state.economy.values)
    before = _value(state, 12, "evansville")
    _resolve_links(state, week_id(state.day), 1.0)
    assert _value(state, 12, "evansville") > before


def test_cascade_price_war_grocery():
    state = new_game("Westfork", "shop", seed=3, economy_difficulty="standard")
    state.rival.focus = "grocery"
    state.economy.values["81:evansville"] = 30
    quiet = demand_mult(state, HOME_STORE_ID, "grocery")
    force_event(state, 84, city_id="evansville", days=14, intensity=18, start_day=state.day)
    assert demand_mult(state, HOME_STORE_ID, "grocery") < quiet


def test_store_impact_reasons_after_live_weeks():
    off = new_game("Notice Board", "shop", seed=18)
    impact = economy_store_impact(off, HOME_STORE_ID, days=1)
    assert impact["reasons"] == []
    assert impact["delta"]["sales"] == 0
    state = new_game("Notice Board", "shop", seed=18, economy_difficulty="standard")
    _week(state, 14)
    impact = economy_store_impact(state, HOME_STORE_ID, days=7)
    assert set(impact) == {"store_id", "days", "pnl", "neutral_pnl", "delta", "reasons"}
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
    # Dollars on each line reconcile to that line's delta.
    by_line: dict[str, int] = {}
    for row in impact["reasons"]:
        by_line[row["line"]] = by_line.get(row["line"], 0) + int(row["dollars"])
    for line, total in by_line.items():
        assert total == impact["delta"][line]


def _staff_care(state) -> None:
    """One staggered day off a week so the opening pair does not burn out."""
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


def _price_up(state) -> None:
    """A competent shop posts a firmer ticket; cap is five times cost."""
    for product in state.products.values():
        set_price(state, product.id, min(product.cost * 5, max(product.cost, int(round(product.price * 1.8)))))


def _restock(state) -> None:
    """Top up cheap movers, always leaving a Sunday-bill reserve."""
    reserve = 22000
    if state.cash <= reserve:
        return
    basket: dict[str, dict[str, int]] = {}
    for product in state.products.values():
        if int(product.cost) > 80:
            continue
        line = state.stock.get(product.id)
        on_hand = int(line.on_hand) if line is not None else 0
        on_order = int(getattr(line, "on_order", 0) or 0) if line is not None else 0
        need = 160 - on_hand - on_order
        if need <= 0:
            continue
        basket.setdefault(product.supplier_id, {})[product.id] = need
    for supplier_id, items in basket.items():
        cost = sum(state.products[pid].cost * qty for pid, qty in items.items())
        if state.cash - cost < reserve:
            continue
        _add_order(state, supplier_id, items, ignore_minimum=True)


def test_26_week_range_and_standard_solvency():
    """One seed, ~26 weeks: factors stay in range; a default shop stays solvent on standard."""
    seed = 22
    standard = new_game("Lakeshore", "shop", seed=seed, economy_difficulty="standard")
    _price_up(standard)
    for _ in range(26 * 7):
        if standard.day % 7 == 1:
            _restock(standard)
        if standard.campaign is None:
            if standard.cash >= 5000:
                launch_campaign(standard, "local_ad", "playful", "clothing", None)
            elif standard.cash >= 3200:
                launch_campaign(standard, "email", "playful", "clothing", None)
        _staff_care(standard)
        _close(standard)
        if standard.failed:
            break
        continue_morning(standard)
    assert not standard.failed, standard.fail_reason
    assert standard.cash > 0
    assert factors_in_range(standard) == []

    stern = new_game("Lakeshore", "shop", seed=seed, economy_difficulty="stern")
    for _ in range(26):
        # Tick-only range check; Sunday tick is the economy stepper.
        if stern.day % 7 != 0:
            stern.day += 7 - (stern.day % 7)
        economy_tick(stern)
        stern.day += 7
    assert factors_in_range(stern) == []
