"""The minds read the game's costs and factor card, and the holes the stand-in left open."""

from __future__ import annotations

import time

from open_late.ai.actors.ceo import choose_ceo_action
from open_late.ai.actors.others import board_actions, town_actions
from open_late.ai.costs import city_opening_cost, traffic_mult, weekly_rent
from open_late.ai.forecast import project_action
from open_late.ai.constants import PLAYER_TYPES
from open_late.ai.memory import belief_means
from open_late.ai.models import (
    Action,
    ActorMemory,
    ActorRef,
    ChainPnL,
    GameEvent,
    RivalChain,
    RivalStore,
)
from open_late.ai.personalities import load_personalities
from open_late.ai.shoppers import load_segments
from open_late.corporate import MARKETS
from open_late.standin.sim import apply_actions, make_snapshot, simulate


def test_opening_cost_uses_the_market_and_factor_95():
    base = city_opening_cost("seattle", {"95:seattle": 100})
    assert base == MARKETS["seattle"].opening_cost
    assert base == 55_000 * 15
    hot = city_opening_cost("seattle", {"95:seattle": 140})
    assert hot == int(round(base * 1.4))
    cool = city_opening_cost("houston", {"95:houston": 90})
    assert cool == int(round(MARKETS["houston"].opening_cost * 0.9))
    assert city_opening_cost("evansville", {"95:evansville": 100}) == 0


def test_rent_reads_factor_88():
    calm = weekly_rent("seattle", {"88:seattle": 100, "89:seattle": 100})
    assert calm == MARKETS["seattle"].rent_weekly
    hot = weekly_rent("seattle", {"88:seattle": 130, "89:seattle": 100})
    assert hot == int(round(calm * 1.06))


def test_road_work_cuts_the_forecast():
    people, _digest = load_personalities()
    person = people["price_leader_v1"]
    chain = RivalChain(
        chain_id="valuemax",
        personality_id=person.id,
        price_index=92,
        cash=20_000_000,
        stores=[
            RivalStore(
                id="store:valuemax:houston:1",
                city="houston",
                opened_on=1,
                status="open",
                price_index=92,
            )
        ],
    )
    market = [
        {
            "id": "store:valuemax:houston:1",
            "city": "houston",
            "owner": "rival",
            "chain_id": "valuemax",
            "price_index": 92,
            "distance_band": 1,
            "trust": 50,
            "promo": 0,
            "stockouts": 0,
        },
        {
            "id": "evansville",
            "city": "houston",
            "owner": "player",
            "chain_id": "player",
            "price_index": 100,
            "distance_band": 1,
            "trust": 60,
            "promo": 0,
            "stockouts": 0,
        },
    ]
    segments = load_segments()
    quiet = project_action(
        chain,
        gross_margin_bps=person.gross_margin_bps,
        opex_bps=person.opex_bps,
        market=market,
        segments=segments,
        factors={"17:houston": 0},
    )
    torn = project_action(
        chain,
        gross_margin_bps=person.gross_margin_bps,
        opex_bps=person.opex_bps,
        market=market,
        segments=segments,
        factors={"17:houston": 1},
    )
    assert traffic_mult({"17:houston": 1}, "houston") < traffic_mult({"17:houston": 0}, "houston")
    assert torn.sales < quiet.sales


def test_a_broke_chain_cannot_open_on_credit():
    snap, _provider = make_snapshot(1, difficulty="calm")
    assert snap.ai is not None
    chain = next(iter(snap.ai.chains.values()))
    cost = city_opening_cost("seattle", snap.factors)
    chain.cash = cost - 1
    chain.debt = 0
    action = Action(
        actor=ActorRef(kind="ceo", id=f"ceo:{chain.chain_id}"),
        kind="open_store",
        args={"city": "seattle", "site_band": 2, "cost": cost},
        reason="ValueMax filed to open a store in Seattle.",
    )
    result = apply_actions(snap, [action])[0]
    assert result.accepted is False
    assert chain.debt == 0
    people, _digest = load_personalities()
    person = people[chain.personality_id]
    chain.cooldowns = {}
    chosen = choose_ceo_action(
        chain,
        person,
        ActorMemory(actor_id=f"ceo:{chain.chain_id}"),
        seed=1,
        week=1,
        difficulty="calm",
        opening_cost=cost,
        wars={},
        player_price={"seattle": 100},
        opening_costs={"seattle": cost, "houston": cost, "las_vegas": cost, "naperville": cost},
    )
    assert chosen.kind != "open_store"


def test_negative_cash_draws_the_credit_line():
    people, _digest = load_personalities()
    person = people["premium_v1"]
    chain = RivalChain(
        chain_id="bluestar",
        personality_id=person.id,
        price_index=109,
        cash=-200_000,
        debt=0,
        credit_line=10_000_000,
        stores=[],
    )
    chosen = choose_ceo_action(
        chain,
        person,
        ActorMemory(actor_id="ceo:bluestar"),
        seed=1,
        week=3,
        difficulty="calm",
        opening_cost=800_000,
        wars={},
        player_price={},
    )
    assert chosen.kind == "raise_capital"
    assert int(chosen.args["amount"]) > 0


def test_every_acting_chain_learns_a_price_move():
    snap, provider = make_snapshot(4, difficulty="calm")
    assert snap.ai is not None
    acting = list(snap.ai.chains)
    assert len(acting) >= 2
    provider.on_event(
        snap,
        GameEvent(name="PlayerBasketIndex", day=8, week=2, city="houston", payload={"index": 90}),
    )
    for chain_id in acting:
        memory = snap.ai.memories[f"ceo:{chain_id}"]
        assert memory.ref_price.get("houston") == 90
        prior = belief_means({name: 1.0 for name in PLAYER_TYPES})
        assert belief_means(memory.belief)["price_fighter"] > prior["price_fighter"]


def test_board_fires_a_ceo_who_misses_the_margin():
    people, _digest = load_personalities()
    person = people["expander_v1"]
    chain = RivalChain(
        chain_id="shopgiant",
        personality_id=person.id,
        price_index=98,
        cash=5_000_000,
        last_pnl=ChainPnL(week=12, sales=1_000_000, net=-40_000),
    )
    memory = ActorMemory(actor_id="board:shopgiant")
    first = board_actions(chain, memory, person, seed=1, week=13, personalities=people)
    assert all(action.kind != "replace_ceo" for action in first)
    assert memory.counters["quarters_under"] == 1
    second = board_actions(chain, memory, person, seed=1, week=26, personalities=people)
    fired = [action for action in second if action.kind == "replace_ceo"]
    assert fired
    assert fired[0].args["personality_id"] != person.id


def test_town_rule_changes_a_factor_the_forecast_reads():
    snap, _provider = make_snapshot(1, difficulty="calm")
    actions = town_actions(seed=snap.seed, week=4, day=22, permits=[], factors=dict(snap.factors))
    rules = [action for action in actions if action.kind != "permit"]
    assert rules and rules[0].kind == "schedule_road_work"
    before = traffic_mult(snap.factors, "houston")
    apply_actions(snap, rules)
    assert snap.factors["17:houston"] == 1
    assert traffic_mult(snap.factors, "houston") < before


def test_discount_and_premium_do_not_move_alike():
    result = simulate(3, weeks=16, difficulty="calm")
    leader = result.kinds_by_archetype["price_leader"]
    premium = result.kinds_by_archetype["premium"]
    assert leader != premium


def test_stern_sunday_fits_the_budget():
    snap, provider = make_snapshot(1, difficulty="stern")
    provider.weekly(snap)
    times = []
    for _ in range(4):
        started = time.perf_counter()
        provider.weekly(snap)
        times.append((time.perf_counter() - started) * 1000)
    assert sum(times) / len(times) <= 150
    assert max(times) <= 400
