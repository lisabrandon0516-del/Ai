"""Resolver tests for the failure points that matter."""

from __future__ import annotations

from open_late.books import inventory_on_hand, inventory_on_order
from open_late.content import SUPPLIERS
from open_late.engine import (
    answer,
    blocking,
    close_day,
    continue_morning,
    hire,
    launch_campaign,
    new_game,
    offer_raise,
    open_site,
    place_order,
    _add_order,
    return_chance,
    set_assignment,
    set_supplier_terms,
    staff_by_id,
    schedule_event,
)
from open_late.finance import CREW_MULT,  freight_for, pay_advice, payroll_parts, shipping_for, weekly_depreciation, weekly_obligations
from open_late.store import SaveStore


def _clear(state) -> None:
    for message in list(blocking(state)):
        for choice in message.choices:
            answer(state, message.id, choice.id)
            current = next(item for item in state.inbox if item.id == message.id)
            if current.resolved:
                break


def _empty_stock(state) -> None:
    for line in state.stock.values():
        line.on_hand = 0
        line.sizes = {}


def test_over_order_ties_up_cash():
    state = new_game("Ledger", "shop", seed=1)
    before = state.cash
    message = place_order(state, "playnook", {"toy-blocks": 1700, "toy-puzzle": 40})
    assert "Order placed" in message
    merchandise = 1700 * state.products["toy-blocks"].cost + 40 * state.products["toy-puzzle"].cost
    freight = freight_for(SUPPLIERS["playnook"].lead_time_days, merchandise)
    assert state.cash == before - merchandise - freight
    assert state.stock["toy-blocks"].on_order == 1700
    assert state.cash > 0


def test_supplier_minimum_and_credit_wall():
    state = new_game("Ledger", "shop", seed=1)
    before = state.cash
    message = place_order(state, "sparklane", {"elec-radio": 2})
    assert "minimum" in message
    assert state.cash == before
    state.cash = 100
    refused = place_order(state, "sparklane", {"elec-radio": 2200})
    assert "Credit does not pay" in refused
    assert state.cash == 100
    assert state.credit_used == 0


def test_unwilling_modeling_ends_in_a_quit():
    state = new_game("Ledger", "shop", seed=2)
    jordan = staff_by_id(state, "jordan")
    assert jordan is not None
    jordan.reliability = 100
    for _ in range(6):
        if not jordan.employed:
            break
        set_assignment(state, "jordan", "modeling")
        set_assignment(state, "alyssa", "floor")
        _clear(state)
        assert close_day(state) == ""
        if jordan.employed and not state.failed:
            continue_morning(state)
    assert jordan.employed is False
    assert jordan.burnout >= 100
    assert any(message.kind == "quit" for message in state.inbox)


def test_bad_toys_come_back_as_returns():
    state = new_game("Ledger", "shop", seed=3)
    _empty_stock(state)
    state.stock["toy-blocks"].on_hand = 50
    state.flags.policy = "lean_in"
    state.reputation_nightlife = 85
    state.sites[0].foot_traffic = 40
    start_review = state.review_score
    for _ in range(8):
        _clear(state)
        set_assignment(state, "alyssa", "floor")
        set_assignment(state, "jordan", "floor")
        assert close_day(state) == ""
        if state.failed:
            break
        continue_morning(state)
    assert state.totals.returns > 0
    assert state.review_score < start_review


def test_event_against_a_boundary_is_an_incident():
    state = new_game("Ledger", "shop", seed=4)
    message = schedule_event(state, "couples", "jordan", False, "toys")
    assert "does not host" in message
    assert close_day(state) == ""
    assert state.last_report.incident is True
    assert "does not host" in state.last_report.event_blurb
    assert any(message.kind == "incident" and message.urgent for message in state.inbox)


def test_expansion_refuses_a_thin_drawer():
    state = new_game("Ledger", "shop", seed=5)
    state.reputation_nightlife = 80
    state.cash = 100
    message = open_site(state, "nightlife")
    assert "left" in message
    assert state.cash == 100
    assert all(site.id != "nightlife" for site in state.sites)


def test_two_short_sundays_end_the_lease():
    state = new_game("Ledger", "shop", seed=6)
    _empty_stock(state)
    state.cash = 0
    state.credit_limit = 0
    state.day = 7
    assert close_day(state) == ""
    assert state.flags.shortfalls == 1
    assert state.failed is False
    _clear(state)
    _empty_stock(state)
    state.cash = 0
    state.phase = "desk"
    state.day = 14
    assert close_day(state) == ""
    assert state.failed is True
    assert "Two Sundays" in state.fail_reason


def test_save_roundtrip(tmp_path):
    state = new_game("Night Window", "online", seed=7)
    state.cash -= 25
    store = SaveStore(tmp_path / "saves.sqlite")
    store.save(state)
    loaded = store.load(state.slot)
    assert loaded.shop_name == "Night Window"
    assert loaded.mode == "online"
    assert loaded.cash == state.cash
    assert loaded.flags.online_open is True
    assert loaded.model_dump() == state.model_dump()
    listed = store.list_saves()
    assert listed[0][0] == state.slot
    store.delete(state.slot)
    assert store.list_saves() == []


def test_social_post_against_a_limit_raises_burnout():
    state = new_game("Ledger", "shop", seed=8)
    jordan = staff_by_id(state, "jordan")
    assert jordan is not None
    before = jordan.burnout
    message = launch_campaign(state, "social", "discreet", "clothing", "jordan")
    assert "did not want the camera" in message
    assert jordan.assignment == "modeling"
    assert close_day(state) == ""
    assert jordan.burnout >= before + 26


def test_sensible_month_does_not_collapse():
    state = new_game("Ledger", "shop", seed=1)
    for _ in range(28):
        if state.phase == "evening":
            continue_morning(state)
        if state.failed:
            break
        for person in state.staff:
            if not person.employed:
                continue
            if person.aptitude_fulfillment > person.aptitude_floor + 20:
                set_assignment(state, person.id, "fulfillment")
            else:
                set_assignment(state, person.id, "floor")
        tired = [person for person in state.staff if person.employed and person.burnout >= 52]
        floor = [person for person in state.staff if person.employed and person.assignment == "floor"]
        if tired and len(floor) > 1:
            resting = max(tired, key=lambda person: person.burnout)
            set_assignment(state, resting.id, "off")
        _clear(state)
        _restock(state)
        error = close_day(state)
        assert error == "", error
    assert state.failed is False, state.fail_reason + "\n" + "\n".join(state.journal[-4:])
    assert state.cash > 500
    assert state.day == 28


def _restock(state) -> None:
    reserve = weekly_obligations(state) + 8000
    if state.cash <= reserve:
        return
    budget = int((state.cash - reserve) * 0.45)
    by_supplier: dict[str, dict[str, int]] = {}
    for product in state.products.values():
        if product.quality < 3 or product.cost > 80:
            continue
        line = state.stock[product.id]
        if line.on_hand + line.on_order >= 80:
            continue
        qty = 120 - (line.on_hand + line.on_order)
        cost = product.cost * qty
        if cost > budget:
            continue
        by_supplier.setdefault(product.supplier_id, {})[product.id] = qty
        budget -= cost
    for supplier_id, lines in by_supplier.items():
        _add_order(state, supplier_id, lines, ignore_minimum=True)


def test_cash_order_keeps_the_position():
    state = new_game("Ledger", "shop", seed=11)
    before = state.cash + inventory_on_hand(state) + inventory_on_order(state)
    message = place_order(state, "soapstone", {"house-towels": 2500})
    assert "paid from the drawer" in message
    after = state.cash + inventory_on_hand(state) + inventory_on_order(state)
    merchandise = 2500 * state.products["house-towels"].cost
    freight = freight_for(SUPPLIERS["soapstone"].lead_time_days, merchandise)
    assert before - after == freight


def test_net_terms_do_not_spend_cash_until_due():
    state = new_game("Ledger", "shop", seed=12)
    account = next(item for item in state.supplier_accounts if item.supplier_id == "playnook")
    account.relationship = 60
    opened = set_supplier_terms(state, "playnook", "net14")
    assert "net 14" in opened
    before = state.cash
    message = place_order(state, "playnook", {"toy-blocks": 1800})
    cost = 1800 * state.products["toy-blocks"].cost
    freight = freight_for(SUPPLIERS["playnook"].lead_time_days, cost)
    assert "on net 14" in message
    assert state.cash == before
    assert account.payable == cost + freight
    state.orders[-1].arrives_on = 400
    state.day = account.due_day
    state.phase = "desk"
    _empty_stock(state)
    assert close_day(state) == ""
    assert account.payable == 0
    assert state.cash == before - cost - freight


def test_tax_is_held_then_sent_on_sunday():
    state = new_game("Ledger", "shop", seed=13)
    _clear(state)
    assert close_day(state) == ""
    held = state.tax_held
    assert state.last_report.tax_collected > 0
    assert held > 0
    for _ in range(6):
        continue_morning(state)
        _clear(state)
        set_assignment(state, "alyssa", "floor")
        set_assignment(state, "jordan", "floor")
        assert close_day(state) == ""
    assert state.day == 7
    assert state.last_report.tax_remitted > 0
    assert state.tax_held == 0
    assert state.tax_lifetime >= held


def test_training_raises_knowledge():
    state = new_game("Ledger", "shop", seed=14)
    alyssa = staff_by_id(state, "alyssa")
    assert alyssa is not None
    before = alyssa.product_knowledge
    set_assignment(state, "alyssa", "training")
    set_assignment(state, "jordan", "floor")
    _clear(state)
    assert close_day(state) == ""
    assert alyssa.product_knowledge == before + 2
    assert alyssa.sales_attributed == 0


def test_coverage_records_lost_visits():
    state = new_game("Ledger", "shop", seed=15)
    # Empty-floor cap is 20 * CREW_MULT; send enough traffic to overflow it.
    state.sites[0].foot_traffic = 800
    for person in state.staff:
        if person.employed:
            set_assignment(state, person.id, "off")
    _clear(state)
    assert close_day(state) == ""
    report = state.last_report
    assert report.capacity < report.visits
    assert report.lost_staff > 0


def test_quarter_close_writes_a_statement():
    state = new_game("Ledger", "shop", seed=16)
    state.day = 28
    _clear(state)
    assert close_day(state) == ""
    assert state.months
    assert state.months[-1].day == 28
    assert any(target.closed for target in state.targets)
    assert any(not target.closed and target.due_day == 56 for target in state.targets)


def test_raise_changes_the_wage():
    state = new_game("Ledger", "shop", seed=17)
    jordan = staff_by_id(state, "jordan")
    assert jordan is not None
    before = jordan.wage
    message = offer_raise(state, "jordan")
    assert jordan.wage > before
    assert str(jordan.wage) in message or "week" in message
    assert jordan.review_due == state.day + 28


def test_pay_advice_splits_a_week_like_a_voucher():
    state = new_game("Ledger", "shop", seed=4)
    jordan = staff_by_id(state, "jordan")
    assert jordan is not None
    jordan.employed = False
    alyssa = staff_by_id(state, "alyssa")
    assert alyssa is not None
    alyssa.wage = 600
    state.open_hour = 12
    state.close_hour = 16
    advice = pay_advice(state, alyssa)
    assert advice.regular_hours == 20
    assert advice.overtime_hours == 0
    assert advice.rate_cents == 1500
    assert advice.gross == 300
    assert advice.federal == 0
    assert advice.social == 18
    assert advice.medicare == 4
    assert advice.state_tax == 8
    assert advice.county_tax == 3
    assert advice.net == 300 - 18 - 4 - 8 - 3
    full = new_game("Ledger", "shop", seed=4)
    alyssa = staff_by_id(full, "alyssa")
    assert alyssa is not None
    week = pay_advice(full, alyssa)
    assert week.regular_hours == 40
    assert week.rate_cents == 3800
    assert week.gross == 1520
    assert week.federal > 0
    withheld = week.federal + week.social + week.medicare + week.state_tax + week.county_tax
    assert week.net + withheld == week.gross
    full.day = 7
    full.phase = "desk"
    _clear(full)
    assert close_day(full) == ""
    assert alyssa.ytd_gross == 1520
    assert alyssa.ytd_net == week.net


def test_costs_behave_like_a_shop():
    state = new_game("Ledger", "shop", seed=18)
    wages, payroll_tax = payroll_parts(state)
    assert wages == (1520 + 1600 + 1560 + 1680 + 1760 + 1920) * CREW_MULT
    assert payroll_tax == (wages * 765) // 10000
    state.close_hour = 21
    overtime, _tax = payroll_parts(state)
    assert overtime > wages
    tee = state.stock["cloth-tee"]
    assert sum(tee.sizes.values()) == tee.on_hand
    assert len(tee.sizes) > 1
    tablet = state.products["elec-tablet"]
    pasta = state.products["groc-pasta"]
    assert shipping_for(tablet) > shipping_for(pasta)
    assert 0 < return_chance(state.products["toy-puzzle"]) < 0.08
    assert 0.1 < return_chance(state.products["toy-blocks"]) < 0.25
    assert weekly_depreciation(2400, 0) < 20


def test_hire_starts_on_the_sheet():
    state = new_game("Ledger", "shop", seed=9)
    message = hire(state, "evan")
    assert "Evan" in message
    evan = staff_by_id(state, "evan")
    assert evan is not None and evan.employed is True
