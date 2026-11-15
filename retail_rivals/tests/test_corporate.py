"""The office owns the doors. Managers run the floors."""

from __future__ import annotations

from open_late.engine import (
    answer,
    blocking,
    close_day,
    continue_morning,
    hire,
    new_game,
    place_order,
    set_assignment,
    staff_by_id,
)
from open_late.finance import SIZE_MULT, freight_for, pay_advice
from open_late.content import SUPPLIERS


def _afford(state, city: str) -> None:
    from open_late.corporate import MARKETS

    market = MARKETS[city]
    state.cash = market.opening_cost + market.min_cash_after + 1


def _clear(state) -> None:
    for message in list(blocking(state)):
        for choice in message.choices:
            answer(state, message.id, choice.id)
            current = next(item for item in state.inbox if item.id == message.id)
            if current.resolved:
                break


def _door(state, door_id: str):
    return next(door for door in state.doors if door.id == door_id)


def test_shop_is_unchanged():
    state = new_game("Ledger", "shop", seed=1)
    assert state.mode == "shop"
    assert state.doors == []
    assert state.managers == []


def test_corporate_opens_on_evansville_with_a_manager():
    state = new_game("Toy's N Us", "corporate", seed=3)
    assert state.mode == "corporate"
    assert [door.id for door in state.doors] == ["evansville"]
    door = state.doors[0]
    assert door.city == "Evansville"
    assert door.state_name == "Indiana"
    assert door.sales_tax_bps == 700
    assert door.manager_id == "dana"
    dana = next(person for person in state.managers if person.id == "dana")
    assert dana.employed and dana.door_id == "evansville"
    assert any(site.is_warehouse for site in state.sites)
    assert state.stock["cloth-tee"].on_hand > 0
    assert door.stock["cloth-tee"].on_hand > 0
    alyssa = staff_by_id(state, "alyssa")
    assert alyssa is not None and alyssa.employed and alyssa.door_id == "evansville"


def test_openable_markets_are_the_other_four_cities():
    from open_late.corporate import openable_markets

    state = new_game("Toy's N Us", "corporate", seed=3)
    names = {market.city for market in openable_markets(state)}
    assert names == {"Seattle", "Houston", "Las Vegas", "Naperville"}


def test_manager_writes_the_schedule():
    state = new_game("Toy's N Us", "corporate", seed=3)
    message = set_assignment(state, "alyssa", "off")
    assert "Dana" in message
    assert "schedule" in message
    alyssa = staff_by_id(state, "alyssa")
    assert alyssa is not None
    alyssa.assignment = "off"
    _clear(state)
    assert close_day(state) == ""
    alyssa = staff_by_id(state, "alyssa")
    assert alyssa is not None
    assert alyssa.assignment == "floor"
    assert state.last_report.revenue > 0
    assert state.last_report.tax_collected > 0
    assert any("7%" in note or "Evansville" in note for note in state.last_report.notes)


def test_suburb_lease_keeps_the_intense_wall_off():
    from open_late.corporate import open_market, set_planogram

    state = new_game("Toy's N Us", "corporate", seed=3)
    _afford(state, "naperville")
    assert "Naperville" in open_market(state, "naperville")
    refused = set_planogram(state, "naperville", _shares(pharmacy=12))
    assert "lease" in refused.lower()
    accepted = set_planogram(state, "naperville", _shares(pharmacy=0))
    assert accepted == ""
    door = _door(state, "naperville")
    assert door.planogram["pharmacy"] == 0
    assert sum(door.planogram.values()) == 100
    assert door.allows_intense is False


def test_truck_is_in_transit_until_the_zone_day():
    from open_late.corporate import allocate, transfer_freight
    from open_late.models import DayReport

    state = new_game("Toy's N Us", "corporate", seed=3)
    state.stock["house-towels"].on_hand = 10
    state.stock["house-towels"].sizes = {}
    door = _door(state, "evansville")
    before_door = door.stock["house-towels"].on_hand
    before_cash = state.cash
    message = allocate(state, "evansville", {"house-towels": 4})
    assert "freight" in message.lower()
    assert "arrives" in message.lower()
    assert state.stock["house-towels"].on_hand == 6
    assert door.stock["house-towels"].on_hand == before_door
    assert state.cash == before_cash - transfer_freight(door, 4)
    assert state.shipments[0].arrives_on == state.day + door.transit_days
    refused = allocate(state, "evansville", {"house-towels": 100})
    assert "warehouse" in refused.lower()
    assert state.stock["house-towels"].on_hand == 6
    state.day = state.shipments[0].arrives_on
    from open_late.corporate import receive_shipments

    receive_shipments(state, DayReport())
    assert door.stock["house-towels"].on_hand == before_door + 4
    assert state.shipments == []


def test_long_haul_damages_units_and_a_full_store_sends_the_rest_back():
    from open_late.corporate import allocate, holding_capacity, open_market, receive_shipments
    from open_late.models import DayReport

    state = new_game("Toy's N Us", "corporate", seed=8)
    _afford(state, "seattle")
    open_market(state, "seattle")
    door = _door(state, "seattle")
    state.stock["house-towels"].on_hand = 40
    state.stock["house-towels"].sizes = {}
    allocate(state, "seattle", {"house-towels": 40})
    shipment = state.shipments[-1]
    assert shipment.arrives_on == state.day + 6
    state.day = shipment.arrives_on
    receive_shipments(state, DayReport())
    damaged = 40 * (door.transit_days - 2) // 40
    assert damaged == 4
    assert door.stock["house-towels"].on_hand == 40 - damaged

    home = _door(state, "evansville")
    home.stock["house-bags"].on_hand = holding_capacity(home)
    state.stock["house-bags"].on_hand = 10
    state.stock["house-bags"].sizes = {}
    allocate(state, "evansville", {"house-bags": 10})
    state.day = state.shipments[-1].arrives_on
    report = DayReport()
    receive_shipments(state, report)
    assert home.stock["house-bags"].on_hand == holding_capacity(home)
    assert state.stock["house-bags"].on_hand == 10
    assert any("capacity" in note.lower() for note in report.notes)


def test_a_new_city_does_not_sell_during_build_out():
    from open_late.corporate import open_market

    state = new_game("Toy's N Us", "corporate", seed=9)
    _afford(state, "houston")
    message = open_market(state, "houston")
    assert "build-out" in message.lower()
    door = _door(state, "houston")
    assert door.status == "buildout"
    assert door.opens_on == state.day + 10
    door.stock["house-towels"].on_hand = 30
    _clear(state)
    assert close_day(state) == ""
    assert door.last_sales == 0
    assert any("build-out" in note.lower() for note in state.last_report.notes)


def test_manager_keeps_the_shift_inside_the_labor_budget():
    state = new_game("Toy's N Us", "corporate", seed=3)
    door = _door(state, "evansville")
    door.labor_budget = 1600 * SIZE_MULT
    _clear(state)
    assert close_day(state) == ""
    jordan = staff_by_id(state, "jordan")
    alyssa = staff_by_id(state, "alyssa")
    assert jordan is not None and alyssa is not None
    assert jordan.assignment == "floor"
    assert alyssa.assignment == "off"


def test_coop_accrues_on_receipts_and_is_claimed_on_an_ad():
    from open_late.corporate import sign_deal
    from open_late.engine import CAMPAIGN_COST, launch_campaign

    state = new_game("Toy's N Us", "corporate", seed=6)
    account = next(item for item in state.supplier_accounts if item.supplier_id == "soapstone")
    account.volume = 1_500
    sign_deal(state, "soapstone")
    place_order(state, "soapstone", {"house-towels": 2605})
    merchandise = state.products["house-towels"].cost * 2605 * 96 // 100
    earned = merchandise * 10 // 100
    deal = next(item for item in state.deals if item.supplier_id == "soapstone")
    assert deal.coop_accrued == earned
    before = state.cash
    message = launch_campaign(state, "local_ad", "discreet", "household", None, "evansville")
    assert "co-op" in message.lower()
    ad_cost = CAMPAIGN_COST["local_ad"]
    claimed = min(earned, ad_cost)
    assert state.cash == before - (ad_cost - claimed)
    assert deal.coop_accrued == earned - claimed


def test_replenishment_ships_weeks_of_supply():
    from open_late.corporate import replenish
    from open_late.models import SalesDay

    state = new_game("Toy's N Us", "corporate", seed=3)
    door = _door(state, "evansville")
    door.stock["house-towels"].on_hand = 0
    door.stock["house-towels"].sizes = {}
    door.weeks_of_supply = 2
    door.sales_days = [SalesDay(day=state.day, units={"house-towels": 7})]
    state.stock["house-towels"].on_hand = 30
    state.stock["house-towels"].sizes = {}
    message = replenish(state, "evansville")
    assert "house-towels" in message.lower() or "14" in message or "oil" in message.lower()
    shipped = state.shipments[-1].lines.get("house-towels", 0)
    assert shipped == 14
    assert state.stock["house-towels"].on_hand == 16


def test_sunday_scores_four_wall_contribution_and_marks_down_old_stock():
    state = new_game("Toy's N Us", "corporate", seed=3)
    product = state.products["cloth-tee"]
    before = product.price
    state.stock["cloth-tee"].age_days = 40
    for _ in range(6):
        _clear(state)
        assert close_day(state) == ""
        continue_morning(state)
    _clear(state)
    assert close_day(state) == ""
    door = _door(state, "evansville")
    assert door.last_week_sales > 0
    assert any("contribution" in note.lower() for note in state.last_report.notes)
    assert product.price < before
    assert product.price >= product.cost


def test_seattle_wage_floor_and_schedule_change_penalty():
    from open_late.corporate import assign_door, open_market, set_door_hours

    state = new_game("Toy's N Us", "corporate", seed=4)
    _afford(state, "seattle")
    open_market(state, "seattle")
    placed = assign_door(state, "priya", "seattle")
    priya = staff_by_id(state, "priya")
    assert priya is not None
    from open_late.finance import size_int

    floor = size_int(1660)
    assert "24,900" in placed or str(floor) in placed
    assert priya.wage >= floor
    assert priya.door_id == "seattle"
    monday = set_door_hours(state, "seattle", 10, 18)
    assert "predictability" not in monday.lower()
    door = _door(state, "seattle")
    assert (door.posted_open, door.posted_close) == (10, 18)
    _clear(state)
    assert close_day(state) == ""
    continue_morning(state)
    _clear(state)
    assert close_day(state) == ""
    continue_morning(state)
    assert state.day == 3
    changed = set_door_hours(state, "seattle", 11, 20)
    assert "predictability" in changed.lower()
    assert door.predictability_due > 0
    advice = pay_advice(state, priya)
    assert advice.state_tax == 0
    assert advice.county_tax == 0


def test_vegas_weekend_is_busier_than_a_monday():
    from open_late.corporate import crowd_factor, open_market

    state = new_game("Toy's N Us", "corporate", seed=3)
    _afford(state, "las_vegas")
    open_market(state, "las_vegas")
    door = _door(state, "las_vegas")
    state.day = 1
    monday = crowd_factor(state, door)
    state.day = 5
    friday = crowd_factor(state, door)
    assert friday > monday


def test_houston_has_no_state_income_tax_on_the_voucher():
    from open_late.corporate import assign_manager, hire_manager, open_market

    state = new_game("Toy's N Us", "corporate", seed=5)
    _afford(state, "houston")
    open_market(state, "houston")
    hire_manager(state, "owen")
    assign_manager(state, "owen", "houston")
    hire(state, "chris")
    from open_late.corporate import assign_door

    assign_door(state, "chris", "houston")
    chris = staff_by_id(state, "chris")
    assert chris is not None
    advice = pay_advice(state, chris)
    assert advice.state_tax == 0
    assert _door(state, "houston").state_tax_per_ten_thousand == 0


def test_volume_deal_cuts_the_cost_and_opens_net_30():
    from open_late.corporate import sign_deal

    state = new_game("Toy's N Us", "corporate", seed=6)
    refused = sign_deal(state, "soapstone")
    assert "list" in refused.lower()
    account = next(item for item in state.supplier_accounts if item.supplier_id == "soapstone")
    account.volume = 1_500
    signed = sign_deal(state, "soapstone")
    assert "4%" in signed
    assert "net 30" in signed.lower() or "net 14" in signed.lower()
    deal = next(item for item in state.deals if item.supplier_id == "soapstone")
    assert deal.cost_off_percent == 4
    product_cost = state.products["house-towels"].cost
    qty = 2605
    merchandise = product_cost * qty * 96 // 100
    freight = freight_for(SUPPLIERS["soapstone"].lead_time_days, merchandise)
    before = state.cash
    message = place_order(state, "soapstone", {"house-towels": qty})
    assert "net" in message.lower()
    assert state.cash == before
    assert account.payable >= merchandise + freight


def test_a_better_deal_keeps_coop_already_earned():
    from open_late.corporate import sign_deal

    state = new_game("Toy's N Us", "corporate", seed=6)
    account = next(item for item in state.supplier_accounts if item.supplier_id == "soapstone")
    account.volume = 1_500
    sign_deal(state, "soapstone")
    place_order(state, "soapstone", {"house-towels": 2605})
    earned = next(item for item in state.deals if item.supplier_id == "soapstone").coop_accrued
    assert earned > 0
    account.volume = 4_000
    sign_deal(state, "soapstone")
    deal = next(item for item in state.deals if item.supplier_id == "soapstone")
    assert deal.tier == "partner"
    assert deal.coop_accrued == earned


def test_sunday_contribution_counts_predictability_pay():
    from open_late.corporate import week_gross

    state = new_game("Toy's N Us", "corporate", seed=3)
    door = _door(state, "evansville")
    door.status = "buildout"
    door.opens_on = 99
    door.week_sales = 1_000
    door.week_cogs = 200
    door.week_shrink = 50
    door.week_freight = 10
    door.predictability_due = 200
    state.day = 7
    labor = 200 + door.rent_weekly + door.week_freight
    dana = next(person for person in state.managers if person.id == "dana")
    labor += dana.wage
    for person in state.staff:
        if person.employed and person.door_id == door.id and person.assignment != "off":
            labor += week_gross(person, door)
    expected = door.week_sales - door.week_cogs - door.week_shrink - labor
    _clear(state)
    assert close_day(state) == ""
    assert door.last_contribution == expected


def test_two_doors_raise_sunday_rent():
    from open_late.corporate import open_market

    state = new_game("Toy's N Us", "corporate", seed=7)
    first = sum(site.rent_weekly for site in state.sites)
    state.cash = 100
    blocked = open_market(state, "houston")
    assert "drawer" in blocked.lower()
    assert len(state.doors) == 1
    _afford(state, "houston")
    open_market(state, "houston")
    assert sum(site.rent_weekly for site in state.sites) > first


def _shares(pharmacy: int) -> dict[str, int]:
    grocery = 14 + (5 - pharmacy)
    return {
        "grocery": grocery,
        "produce": 8,
        "meat_dairy": 9,
        "frozen": 7,
        "household": 9,
        "health_beauty": 7,
        "pharmacy": pharmacy,
        "electronics": 7,
        "clothing": 8,
        "toys": 6,
        "home_garden": 7,
        "sporting": 6,
        "seasonal": 7,
    }
