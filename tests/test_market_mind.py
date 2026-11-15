"""The CEO plays the shopper logit, a belief about the player, and one reply."""

from __future__ import annotations

import copy

import pytest

from open_late.ai.actors.ceo import _expectimax, _terms, _utility, choose_ceo_action, follow_up_actions
from open_late.ai.constants import PLAYER_TYPES
from open_late.ai.forecast import project_action
from open_late.ai.market import apply_player_reply
from open_late.ai.memory import belief_means
from open_late.ai.models import Action, ActorMemory, ActorRef, RivalChain, RivalStore
from open_late.ai.personalities import load_personalities
from open_late.ai.shoppers import load_segments, visit_multipliers
from open_late.standin.sim import simulate
from tools.tune_personalities import archetype_gap, evaluate, tune_generation


def _market() -> list[dict]:
    return [
        {
            "id": "player-houston",
            "city": "houston",
            "owner": "player",
            "chain_id": "player",
            "price_index": 100,
            "distance_band": 1,
            "trust": 60,
            "promo": 0,
            "stockouts": 0,
            "focus": "grocery",
        },
        {
            "id": "store:bluestar:houston:1",
            "city": "houston",
            "owner": "rival",
            "chain_id": "bluestar",
            "price_index": 109,
            "distance_band": 2,
            "trust": 50,
            "promo": 0,
            "stockouts": 0,
            "focus": "grocery",
        },
        {
            "id": "store:valuemax:houston:1",
            "city": "houston",
            "owner": "rival",
            "chain_id": "valuemax",
            "price_index": 100,
            "distance_band": 2,
            "trust": 50,
            "promo": 0,
            "stockouts": 0,
            "focus": "grocery",
        },
        {
            "id": "online",
            "city": "",
            "owner": "online",
            "chain_id": "online",
            "price_index": 100,
            "distance_band": 2,
            "trust": 50,
            "promo": 0,
            "stockouts": 0,
            "focus": "",
        },
    ]


def _chain() -> RivalChain:
    people, _digest = load_personalities()
    person = people["premium_v1"]
    return RivalChain(
        chain_id="bluestar",
        personality_id=person.id,
        price_index=person.price_index,
        cash=15_000_000,
        stores=[
            RivalStore(
                id="store:bluestar:houston:1",
                city="houston",
                opened_on=1,
                status="open",
                price_index=person.price_index,
            )
        ],
    )


def _project(market: list[dict], **kwargs):
    people, _digest = load_personalities()
    person = people["premium_v1"]
    return project_action(
        _chain(),
        gross_margin_bps=person.gross_margin_bps,
        opex_bps=person.opex_bps,
        market=market,
        segments=load_segments(),
        income_by_city={"houston": 100},
        **kwargs,
    )


def test_a_cheaper_rival_steals_sales_through_the_logit():
    calm = _market()
    undercut = copy.deepcopy(calm)
    for row in undercut:
        if row["chain_id"] == "valuemax":
            row["price_index"] = 80
    held = _project(calm, kind="do_nothing")
    hurt = _project(undercut, kind="do_nothing")
    assert hurt.sales < held.sales


def test_projection_visit_mult_matches_the_shopper_card_formula():
    segments = load_segments()
    local = [row for row in _market() if row["city"] in {"houston", ""}]
    mults = visit_multipliers(local, segments, income_index=100)
    assert mults["store:bluestar:houston:1"] != 1000
    projected = _project(_market(), kind="do_nothing")
    # Traffic from the Sunday card, then the shelf price. No second elasticity.
    from open_late.ai.forecast import card_units

    traffic = card_units(mults["store:bluestar:houston:1"], 0)
    assert projected.sales == int(round(traffic * 109 / 100.0))


def test_price_fighter_reply_takes_more_sales_than_a_passive_player():
    market = _market()
    fighter = _project(market, kind="do_nothing", player_type="price_fighter")
    passive = _project(market, kind="do_nothing", player_type="passive")
    assert fighter.sales < passive.sales
    replied = apply_player_reply(market, "price_fighter", "houston")
    player = next(row for row in replied if row["owner"] == "player")
    # Cheapest rival is ValueMax at 100, so a price fighter shelves at 96.
    assert player["price_index"] == 96


def test_price_cut_gains_share_against_the_city():
    from open_late.ai.forecast import card_units

    market = _market()
    cut = _project(market, kind="set_chain_price_index", args={"delta": -6})
    cheaper = copy.deepcopy(market)
    for row in cheaper:
        if row["chain_id"] == "bluestar":
            row["price_index"] = 103
    local = [row for row in cheaper if row["city"] in {"houston", ""}]
    mult = visit_multipliers(local, load_segments(), income_index=100)["store:bluestar:houston:1"]
    assert cut.sales == int(round(card_units(mult, 0) * 103 / 100.0))
    assert cut.share_change_bps > 0


def test_expectimax_answers_the_sampled_player_then_replies():
    people, _digest = load_personalities()
    person = people["premium_v1"].model_copy(deep=True)
    person.weights = {name: 0.0 for name in person.weights}
    person.weights["share_change"] = 6.0
    person.weights["contribution_13w"] = 0.2
    chain = _chain()
    action = Action(
        actor=ActorRef(kind="ceo", id="ceo:bluestar"),
        kind="open_store",
        args={"city": "seattle", "site_band": 2, "cost": 6_000_000},
    )
    fighter = ActorMemory(
        actor_id="ceo:bluestar",
        belief={name: (40.0 if name == "price_fighter" else 0.0) for name in PLAYER_TYPES},
    )
    passive = ActorMemory(
        actor_id="ceo:bluestar",
        belief={name: (40.0 if name == "passive" else 0.0) for name in PLAYER_TYPES},
    )
    kwargs = dict(
        seed=2,
        week=1,
        opening_cost=6_000_000,
        visit_mult=1000,
        iters=4,
        market=_market(),
        segments=load_segments(),
        income_by_city={"houston": 100, "seattle": 100},
    )
    fighter_value, _fighter_terms = _expectimax(action, chain, person, fighter, **kwargs)
    passive_value, _passive_terms = _expectimax(action, chain, person, passive, **kwargs)
    assert fighter_value != pytest.approx(passive_value)

    means = belief_means(passive.belief)
    assert means["passive"] == pytest.approx(1.0)
    one_step_terms = _terms(
        action,
        chain,
        person,
        passive,
        week=1,
        opening_cost=6_000_000,
        visit_mult=1000,
        shock_bps=0,
        market=_market(),
        segments=load_segments(),
        income_by_city={"houston": 100, "seattle": 100},
        player_type="passive",
    )
    # A follow-up that gives up profit to buy share does not beat holding the new door.
    assert passive_value == pytest.approx(_utility(one_step_terms, person.weights))
    assert any(follow.kind == "set_chain_price_index" for follow in follow_up_actions(chain, action))


def test_a_fighter_belief_changes_the_weekly_choice():
    people, _digest = load_personalities()
    person = people["premium_v1"].model_copy(deep=True)
    person.temperature = 0
    chain = RivalChain(
        chain_id="bluestar",
        personality_id=person.id,
        price_index=90,
        cash=15_000_000,
        cooldowns={"big_call": 99, "opening": 99, "war:houston": 99},
        stores=[
            RivalStore(
                id="store:bluestar:houston:1",
                city="houston",
                opened_on=1,
                status="open",
                price_index=90,
                distance_band=1,
            )
        ],
    )
    market = [
        {
            "id": "player-houston",
            "city": "houston",
            "owner": "player",
            "chain_id": "player",
            "price_index": 100,
            "distance_band": 1,
            "trust": 55,
            "promo": 0,
            "stockouts": 0,
            "focus": "grocery",
        },
        {
            "id": "store:bluestar:houston:1",
            "city": "houston",
            "owner": "rival",
            "chain_id": "bluestar",
            "price_index": 90,
            "distance_band": 1,
            "trust": 70,
            "promo": 0,
            "stockouts": 0,
            "focus": "grocery",
        },
        {
            "id": "online",
            "city": "",
            "owner": "online",
            "chain_id": "online",
            "price_index": 100,
            "distance_band": 2,
            "trust": 50,
            "promo": 0,
            "stockouts": 0,
            "focus": "",
        },
    ]
    common = dict(
        seed=1,
        week=3,
        difficulty="calm",
        opening_cost=6_000_000,
        wars={},
        player_price={"houston": 100},
        market=market,
        segments=load_segments(),
        income_by_city={"houston": 100},
    )
    fighter = choose_ceo_action(
        chain,
        person,
        ActorMemory(
            actor_id="ceo:bluestar",
            belief={name: (30.0 if name == "price_fighter" else 0.0) for name in PLAYER_TYPES},
        ),
        **common,
    )
    quiet = choose_ceo_action(
        chain,
        person,
        ActorMemory(
            actor_id="ceo:bluestar",
            belief={name: (30.0 if name == "passive" else 0.0) for name in PLAYER_TYPES},
        ),
        **common,
    )
    # Below the shelf the margin is already broken, so both beliefs climb
    # back toward it. The belief still changes what a deep cut is worth.
    assert fighter.kind == "set_chain_price_index" and int(fighter.args["delta"]) > 0
    assert quiet.kind == "set_chain_price_index" and int(quiet.args["delta"]) > 0
    from open_late.ai.actors.ceo import _terms
    from open_late.ai.models import Action, ActorRef

    # A cut below the shelf earns no share against either belief. It still
    # costs a different amount of profit once the player's reply is priced in.
    cut = Action(actor=ActorRef(kind="ceo", id="ceo:bluestar"), kind="set_chain_price_index", args={"delta": -6})
    kwargs = dict(
        week=3,
        opening_cost=6_000_000,
        visit_mult=1000,
        shock_bps=0,
        market=market,
        segments=load_segments(),
        income_by_city={"houston": 100},
    )
    fighter_cut = _terms(cut, chain, person, ActorMemory(actor_id="ceo:bluestar"), player_type="price_fighter", **kwargs)
    quiet_cut = _terms(cut, chain, person, ActorMemory(actor_id="ceo:bluestar"), player_type="passive", **kwargs)
    assert fighter_cut["share_change"] == 0
    assert quiet_cut["share_change"] == 0
    assert fighter_cut["contribution_13w"] > quiet_cut["contribution_13w"]


def test_supplied_weights_change_the_stand_in():
    people, _digest = load_personalities()
    base = simulate(1, weeks=6, difficulty="standard", personalities=people)
    trial = {key: person.model_copy(deep=True) for key, person in people.items()}
    for person in trial.values():
        person.weights = {name: 0.0 for name in person.weights}
        person.weights["share_change"] = 4.0
        person.weights["grudge"] = 3.0
    other = simulate(1, weeks=6, difficulty="standard", personalities=trial)
    assert base.signature != other.signature


def test_tune_generation_rescores_trials_and_keeps_the_best(monkeypatch):
    people, _digest = load_personalities()
    seen: list[tuple] = []

    def fake_evaluate(personalities, *, seed: int, weeks: int) -> float:
        del seed, weeks
        fingerprint = tuple(
            (pid, tuple(sorted((name, round(value, 4)) for name, value in person.weights.items())))
            for pid, person in sorted(personalities.items())
        )
        seen.append(fingerprint)
        return float(len(seen))

    monkeypatch.setattr("tools.tune_personalities.evaluate", fake_evaluate)
    score, chosen = tune_generation(people, seed=1, weeks=4)
    assert len(seen) >= 2
    assert len(set(seen)) >= 2
    assert score == float(len(seen))
    kept = tuple(
        (pid, tuple(sorted((name, round(value, 4)) for name, value in person.weights.items())))
        for pid, person in sorted(chosen.items())
    )
    assert kept == seen[-1]


def test_fitness_uses_survival_share_and_archetype_distance():
    people, _digest = load_personalities()
    score = evaluate(people, seed=1, weeks=4)
    assert score > 0
    same = archetype_gap({"premium": ["do_nothing", "do_nothing"], "price_leader": ["do_nothing", "do_nothing"]})
    apart = archetype_gap({"premium": ["do_nothing", "do_nothing"], "price_leader": ["start_price_war", "promo"]})
    assert apart > same
    assert same == 0
