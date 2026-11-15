"""Patch E7a: visible supercenter size pack."""

from __future__ import annotations

from open_late.content import OFFERS, SHOP_STOCK, SIDE_STREET, WANT_GENERAL, WANT_PERISHABLE, WANT_STAPLE, want_units
from open_late.corporate import CREDIT, MARKETS, RESERVE, WAREHOUSE_RENT, holding_capacity
from open_late.engine import _headcount_cap, new_game
from open_late.finance import (
    CALM_RESERVE,
    CALM_RESERVE_BASE,
    CREDIT_LIMIT,
    CREDIT_LIMIT_BASE,
    CREW_MULT,
    SHOP_RESERVE,
    SHOP_RESERVE_BASE,
    SIZE_MULT,
    STERN_RESERVE,
    STERN_RESERVE_BASE,
    payroll_parts,
    size_int,
    size_pack,
    starting_reserve,
)
from open_late.models import Door


def test_size_pack_is_visible_and_scaled():
    assert SIZE_MULT == 15
    assert CREW_MULT == 15
    pack = size_pack()
    assert pack["size_mult"] == 15
    assert pack["credit_limit"] == CREDIT_LIMIT_BASE * 15 == 600_000
    assert pack["shop_reserve"] == SHOP_RESERVE_BASE * 15 == 780_000
    assert pack["calm_reserve"] == CALM_RESERVE_BASE * 15 == 1_020_000
    assert pack["stern_reserve"] == STERN_RESERVE_BASE * 15 == 540_000
    assert starting_reserve("shop", "standard") == SHOP_RESERVE
    assert starting_reserve("shop", "calm") == CALM_RESERVE
    assert starting_reserve("shop", "stern") == STERN_RESERVE
    assert CREDIT_LIMIT == CREDIT_LIMIT_BASE * SIZE_MULT


def test_rent_crews_shelves_and_credit_match_the_pack():
    assert SIDE_STREET.rent_weekly == size_int(4000) == 60_000
    assert OFFERS["side_street"].rent_weekly == 60_000
    assert OFFERS["high_street"].rent_weekly == size_int(9300)
    assert MARKETS["evansville"].rent_weekly == size_int(4700)
    assert WAREHOUSE_RENT == size_int(3000)
    assert RESERVE == size_int(90_000)
    assert CREDIT == size_int(70_000)
    assert sum(SHOP_STOCK.values()) == 363_495
    assert want_units("grocery") == WANT_STAPLE == size_int(250)
    assert want_units("produce") == WANT_PERISHABLE == size_int(200)
    assert want_units("toys") == WANT_GENERAL == size_int(160)
    state = new_game("Prairie Wire", "shop", seed=22, economy_difficulty="standard")
    assert state.cash == SHOP_RESERVE
    assert state.credit_limit == CREDIT_LIMIT
    assert sum(line.on_hand for line in state.stock.values()) == 363_495
    assert sum(site.rent_weekly for site in state.sites) == 60_000
    wages, _tax = payroll_parts(state)
    assert wages == (1520 + 1600 + 1560 + 1680 + 1760 + 1920) * CREW_MULT
    # Six named leads; each is a crew of CREW_MULT, so floor capacity is size-scaled.
    cap = _headcount_cap(state)
    assert cap >= 6
    door = Door(id="evansville", city="Evansville", state_name="Indiana", region="Midwest", planogram={"grocery": 4})
    assert holding_capacity(door) == (400 + 4 * 280) * SIZE_MULT
