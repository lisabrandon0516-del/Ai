"""Core contract tests: rng, fair play, confidence, towns, suppliers, board."""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

from open_late.ai.actors.others import allocate_bps, board_actions, terms_for, town_actions
from open_late.ai.confidence import score_confidence
from open_late.ai.constants import BANNED_WORDS, CHAINS, CITIES
from open_late.ai.explain import (
    CandidateView,
    Consideration,
    combiner_matches,
    eval_curve,
    why_not,
)
from open_late.ai.forecast import project_action
from open_late.ai.memory import belief_means, update_belief
from open_late.ai.migrate import migrate_ai
from open_late.ai.models import Action, ActorMemory, ActorRef, RivalChain, RivalStore, SourceRow
from open_late.ai.observation import build_observation, national_factors
from open_late.ai.personalities import load_personalities, resolve_personalities
from open_late.ai.rng import ai_rng
from open_late.ai.select import argmax, softmax_pick
from open_late.ai.shoppers import choice_shares, load_segments
from open_late.standin.sim import apply_actions, make_snapshot, simulate

ROOT = Path(__file__).resolve().parents[1]


def test_ai_rng_is_stable_and_keyed():
    first = [ai_rng(7, "ai.ceo", 3, "valuemax", "softmax").random() for _ in range(3)]
    second = [ai_rng(7, "ai.ceo", 3, "valuemax", "softmax").random() for _ in range(3)]
    assert first == second
    assert ai_rng(7, "ai.ceo", 3, "valuemax").random() != ai_rng(7, "ai.board", 3, "valuemax").random()
    with pytest.raises(ValueError):
        ai_rng(1, "rng_counter", 1)


def test_off_draws_nothing(monkeypatch):
    def boom(*_args, **_kwargs):
        raise AssertionError("AI drew a random number while off")

    monkeypatch.setattr("open_late.ai.provider.ai_rng", boom)
    snap, provider = make_snapshot(4, difficulty="off", ai_enabled=True)
    assert snap.ai is not None and snap.ai.enabled is False
    assert provider.weekly(snap) == []
    card = provider.shopper_card(snap)
    assert card.visit_mult["evansville"] == 1000
    assert all(value == 1000 for value in card.dept_mult["evansville"].values())


def test_same_seed_same_signature():
    left = simulate(11, weeks=3, difficulty="standard")
    right = simulate(11, weeks=3, difficulty="standard")
    assert left.signature == right.signature
    assert left.reasons_ok


def test_hashseed_does_not_change_the_run():
    code = (
        "from open_late.standin.sim import simulate; "
        "print(simulate(5, weeks=2, difficulty='calm').signature)"
    )
    base = os.environ.copy()
    other = os.environ.copy()
    base["PYTHONHASHSEED"] = "0"
    other["PYTHONHASHSEED"] = "1"
    base["PYTHONPATH"] = str(ROOT / "retail_rivals")
    other["PYTHONPATH"] = str(ROOT / "retail_rivals")
    left = subprocess.check_output([sys.executable, "-c", code], env=base, cwd=ROOT)
    right = subprocess.check_output([sys.executable, "-c", code], env=other, cwd=ROOT)
    assert left == right


def test_player_secrets_do_not_change_rival_actions():
    snap, provider = make_snapshot(9, difficulty="standard")
    other = snap.model_copy(deep=True)
    snap.hidden["player_cash"] = 1
    snap.hidden["orders"] = 0
    other.hidden["player_cash"] = 98_765_432
    other.hidden["orders"] = 400
    left = [action.model_dump() for action in provider.weekly(snap)]
    right = [action.model_dump() for action in provider.weekly(other)]
    assert left == right


def test_observation_hides_o3_and_player_cash():
    factors = national_factors(100)
    factors["46"] = 12345
    factors["102"] = 999
    observation = build_observation(
        seed=1,
        week=2,
        day=8,
        actor=ActorRef(kind="ceo", id="ceo:valuemax"),
        factors=factors,
        public={
            "player_cash": 50,
            "player_price_index": {"houston": 100},
            "player_weekly_sales": {},
            "player_store_cities": {},
        },
        own={"cash": 10},
        cities_with_channel={"houston"},
    )
    assert "46" not in observation.factors
    assert "102" not in observation.factors
    assert observation.factors["23"] == 100
    assert "player_cash" not in observation.public
    assert observation.factor_tier["1"] == "O1"
    assert observation.factor_tier["23"] == "O0"


def test_chain_counts_follow_difficulty():
    for difficulty, count in (("calm", 2), ("standard", 3), ("stern", 4)):
        snap, _provider = make_snapshot(2, difficulty=difficulty)
        assert snap.ai is not None
        assert len(snap.ai.chains) == count
        assert len(snap.ai.roster) == 6
        assert snap.player_chain_id not in snap.ai.roster
        assert set(snap.ai.roster) <= set(CHAINS)
    with pytest.raises(ValueError):
        make_snapshot(1, difficulty="nightmare")


def test_every_reason_is_public_and_short():
    result = simulate(3, weeks=2, difficulty="stern")
    assert result.reasons_ok
    snap, provider = make_snapshot(3, difficulty="stern")
    actions = provider.weekly(snap)
    assert actions
    for action in actions:
        assert 0 < len(action.reason) <= 160
        lowered = action.reason.lower()
        for banned in BANNED_WORDS:
            assert banned not in lowered


def test_confidence_worked_example():
    sources = [
        SourceRow(
            source_kind="market_observe",
            source_id="m1",
            observed_day=24,
            heat_at_observation=34,
            door_id="evansville",
        ),
        SourceRow(
            source_kind="economy_news",
            source_id="n1",
            outlet="Riverbend Desk",
            observed_day=22,
        ),
        SourceRow(source_kind="rumor", source_id="r1", observed_day=23),
    ]
    early = score_confidence(sources, day=24)
    assert early.confidence == 79
    assert early.band == "likely"
    assert early.stale is False
    later = score_confidence(sources, day=36)
    assert later.confidence == 51
    assert later.band == "unconfirmed"
    assert later.stale is True
    empty = score_confidence([], day=10)
    assert empty.confidence is None and empty.band == "unknown"


def test_player_permit_is_not_delayed():
    actions = town_actions(
        seed=5,
        week=2,
        day=8,
        permits=[{"applicant": "player", "city": "houston", "filed_day": 1}],
        factors={"107": 100},
    )
    assert all(action.kind != "permit" for action in actions)


def test_sales_tax_stays_near_neutral():
    factors = {f"104:{city}": 100 for city in ("evansville", "seattle", "houston", "las_vegas", "naperville")}
    factors["14:houston"] = 100
    for week in (13, 26, 39, 52):
        actions = town_actions(seed=3, week=week, day=week * 7, permits=[], factors=factors, doors={"houston": 1})
        for action in actions:
            if action.kind != "sales_tax_drift":
                continue
            city = action.args["cities"][0]
            key = f"104:{city}"
            factors[key] = int(factors.get(key, 100)) + int(action.args["delta"])
    for key, value in factors.items():
        if key.startswith("104:"):
            assert 95 <= value <= 105


def test_towns_delay_and_never_deny():
    permits = [{"applicant": "alpha", "city": "houston", "filed_day": 1}]
    first = town_actions(seed=5, week=2, day=8, permits=permits, factors={"107": 100})
    second = town_actions(seed=5, week=2, day=8, permits=permits, factors={"107": 100})
    assert first[0].args == second[0].args
    assert first[0].args["result"] == "delay"
    assert 2 <= int(first[0].args["weeks"]) <= 8


def test_supplier_terms_are_symmetric():
    assert terms_for(42, 100) == "cash"
    assert terms_for(55, 100) == "net14"
    assert terms_for(70, 1200) == "net30"
    weights = {"player": 42 * 200, "valuemax": 70 * 800}
    swapped = {"valuemax": 70 * 800, "player": 42 * 200}
    assert allocate_bps(weights) == allocate_bps(swapped)
    assert sum(allocate_bps(weights).values()) == 10000


def test_belief_adapts_within_six_updates():
    memory = ActorMemory(actor_id="ceo:valuemax")
    for _ in range(4):
        update_belief(memory, "price_cut")
    assert belief_means(memory.belief)["price_fighter"] > 0.6


def test_board_distress_then_bankruptcy():
    people, _digest = load_personalities()
    person = people["price_leader_v1"]
    chain = RivalChain(chain_id="valuemax", personality_id=person.id, price_index=92, cash=-1000)
    memory = ActorMemory(actor_id="board:valuemax")
    last = []
    for week in range(1, 5):
        last = board_actions(chain, memory, person, seed=1, week=week, personalities=people)
    assert any(action.kind == "declare_distress" for action in last)
    chain.status = "distressed"
    filed = []
    for week in range(5, 13):
        filed = board_actions(chain, memory, person, seed=1, week=week, personalities=people)
    assert any(action.kind == "file_bankruptcy" for action in filed)


def test_overspend_open_is_rejected():
    snap, _provider = make_snapshot(1, difficulty="calm")
    assert snap.ai is not None
    chain_id = next(iter(snap.ai.chains))
    chain = snap.ai.chains[chain_id]
    chain.cash = 0
    chain.debt = chain.credit_line
    action = Action(
        actor=ActorRef(kind="ceo", id=f"ceo:{chain_id}"),
        kind="open_store",
        args={"city": "seattle", "site_band": 2, "cost": snap.opening_cost},
        reason="ValueMax filed to open a store in Seattle.",
    )
    result = apply_actions(snap, [action])[0]
    assert result.accepted is False


def test_shopper_price_elasticity_sign_and_band():
    segments = load_segments()
    low_stores = [
        {"id": "player", "price_index": 100, "distance_band": 1, "trust": 50, "promo": 0, "stockouts": 0},
        {"id": "rival", "price_index": 100, "distance_band": 1, "trust": 50, "promo": 0, "stockouts": 0},
    ]
    high_stores = [
        {"id": "player", "price_index": 110, "distance_band": 1, "trust": 50, "promo": 0, "stockouts": 0},
        {"id": "rival", "price_index": 100, "distance_band": 1, "trust": 50, "promo": 0, "stockouts": 0},
    ]
    low = choice_shares(low_stores, segments)["player"]
    high = choice_shares(high_stores, segments)["player"]
    assert high < low
    price_change = (110 - 100) / ((110 + 100) / 2)
    share_change = (high - low) / ((high + low) / 2)
    elasticity = share_change / price_change
    assert -3.5 <= elasticity <= -1.5


def test_forecast_band_contains_the_point_estimate():
    people, _digest = load_personalities()
    person = people["premium_v1"]
    chain = RivalChain(
        chain_id="bluestar",
        personality_id=person.id,
        price_index=person.price_index,
        cash=15_000_000,
        stores=[
            RivalStore(
                id="store:bluestar:seattle:1",
                city="seattle",
                opened_on=1,
                status="open",
                price_index=person.price_index,
            )
        ],
    )
    projected = project_action(
        chain,
        gross_margin_bps=person.gross_margin_bps,
        opex_bps=person.opex_bps,
    )
    assert projected.p10_contribution <= projected.contribution <= projected.p90_contribution
    assert isinstance(projected.contribution, int)


def test_advisor_does_not_print_exact_rival_cash():
    snap, provider = make_snapshot(6, difficulty="standard")
    assert snap.ai is not None
    chain_id = next(iter(snap.ai.chains))
    snap.ai.chains[chain_id].cash = 12_345_678
    blob = " ".join(f"{note.headline} {note.body}" for note in provider.advise(snap))
    assert "12345678" not in blob
    assert "12,345,678" not in blob


def test_save_roundtrip_and_weight_hash():
    from open_late.ai.models import AIState

    snap, _provider = make_snapshot(8, difficulty="calm")
    assert snap.ai is not None
    again = AIState.model_validate_json(snap.ai.model_dump_json())
    assert again.weights_hash
    people, digest = load_personalities()
    assert again.weights_hash == digest
    _kept, warning = resolve_personalities(again.personalities, people, again.weights_hash, "deadbeef")
    assert warning.startswith("weights_hash mismatch")


def test_migrate_old_save_disables_ai():
    migrated = migrate_ai({"day": 4, "cash": 10})
    assert migrated["ai"]["enabled"] is False
    assert migrated["day"] == 4


def test_tie_break_and_softmax():
    actor = ActorRef(kind="ceo", id="ceo:valuemax")
    hold = Action(actor=actor, kind="do_nothing", args={})
    opening = Action(actor=actor, kind="open_store", args={"city": "seattle", "site_band": 2})
    other = Action(actor=actor, kind="open_store", args={"city": "houston", "site_band": 2})
    assert argmax([(hold, 1.0), (opening, 1.0)]).kind == "open_store"
    assert argmax([(opening, 2.0), (other, 2.0)]).args["city"] == "seattle"
    scored = [
        (Action(actor=actor, kind="do_nothing", args={}), 0.2),
        (Action(actor=actor, kind="cut_costs", args={"pct": 2}), 0.4),
    ]
    left = softmax_pick(scored, ai_rng(3, "ai.ceo", 1, "valuemax", "softmax"), 0.4)
    right = softmax_pick(scored, ai_rng(3, "ai.ceo", 1, "valuemax", "softmax"), 0.4)
    assert left.kind == right.kind


def test_search_uses_a_fixed_iteration_count(monkeypatch):
    calls = []
    real = ai_rng

    def wrapped(*args, **kwargs):
        calls.append(args)
        return real(*args, **kwargs)

    monkeypatch.setattr("open_late.ai.actors.ceo.ai_rng", wrapped)
    from open_late.ai.actors.ceo import _expectimax

    people, _digest = load_personalities()
    person = people["expander_v1"]
    chain = RivalChain(chain_id="shopgiant", personality_id=person.id, price_index=98, cash=15_000_000)
    action = Action(
        actor=ActorRef(kind="ceo", id="ceo:shopgiant"),
        kind="open_store",
        args={"city": "houston", "site_band": 2, "cost": 6_000_000},
    )
    _expectimax(
        action,
        chain,
        person,
        ActorMemory(actor_id="ceo:shopgiant"),
        seed=2,
        week=1,
        opening_cost=6_000_000,
        visit_mult=1000,
        iters=4,
    )
    assert len(calls) == 4
    assert all(call[1] == "ai.search" for call in calls)


def test_gate_draws_cover_every_unused_chain(monkeypatch):
    calls = []
    real = ai_rng

    def wrapped(*args, **kwargs):
        calls.append(args)
        return real(*args, **kwargs)

    monkeypatch.setattr("open_late.ai.provider.ai_rng", wrapped)
    snap, provider = make_snapshot(12, difficulty="calm")
    provider.weekly(snap)
    assert snap.ai is not None
    gates = [call for call in calls if len(call) >= 5 and call[4] == "gate"]
    assert {call[3] for call in gates} == set(snap.ai.roster)


def test_curve_and_why_not():
    assert eval_curve("linear", {"x0": 0, "x1": 30, "y0": 0, "y1": 1}, 12) == pytest.approx(0.4)
    assert combiner_matches(20, 0.4, 8)
    chosen = CandidateView(
        label="cut",
        feasible=True,
        utility=41,
        considerations=[
            Consideration("84", "Price war", 12, 20, 0.4, 8),
            Consideration("heat", "Heat", 34, 1, 1, 10),
        ],
    )
    hold = CandidateView(
        label="hold",
        feasible=True,
        utility=22,
        considerations=[Consideration("84", "Price war", 0, 20, 0, 0)],
    )
    text = why_not(chosen, hold)
    assert "84" in text and "favored" in text
    blocked = CandidateView("open", False, None, "Cash is short.")
    assert why_not(chosen, blocked) == "Cash is short."
    bare = CandidateView("hold", True, 22)
    assert "No consideration breakdown was recorded" in why_not(chosen, bare)


def test_save_stays_under_cap_for_26_weeks():
    from open_late.ai.models import AIState
    from open_late.standin import sim as simmod

    snap, provider = make_snapshot(1, difficulty="stern")
    for _ in range(26):
        actions = provider.weekly(snap)
        simmod.apply_actions(snap, actions)
        provider.shopper_card(snap)
        simmod.settle(snap)
        snap.day += 7
        snap.week += 1
    assert snap.ai is not None
    weeks = {row.week for row in snap.ai.log}
    assert weeks
    assert max(weeks) - min(weeks) <= 25
    raw = snap.ai.model_dump_json()
    assert len(raw.encode("utf-8")) <= 150_000
    loaded = AIState.model_validate_json(raw)
    assert loaded.log[0].result.action.kind == loaded.log[0].action.kind
    assert loaded.log[0].result.accepted is True


def test_no_network_or_engine_rng_in_the_package():
    banned = {"time", "socket", "urllib", "http", "requests", "openai", "asyncio"}
    for path in (ROOT / "retail_rivals" / "open_late" / "ai").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name.split(".")[0] not in banned
            if isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] not in banned
                assert "standin" not in node.module
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "hash":
                raise AssertionError(path)


def test_baselines_cover_the_four_policies():
    from open_late.ai.models import RivalStore
    from tests.ai_baselines import greedy_action, random_action, scripted_action, static_action

    chain = RivalChain(
        chain_id="valuemax",
        personality_id="price_leader_v1",
        price_index=110,
        cash=20_000_000,
        stores=[
            RivalStore(
                id="store:valuemax:houston:1",
                city="houston",
                opened_on=1,
                status="open",
                price_index=110,
            )
        ],
    )
    assert static_action(chain).kind == "do_nothing"
    scripted = scripted_action(chain, week=1, player_index=100, opening_cost=6_000_000, wars={})
    assert scripted.kind == "start_price_war"
    assert scripted.reason
    menu_action = static_action(chain)
    picked = greedy_action(chain, [(menu_action, 10), (scripted, 50)])
    assert picked.kind == "start_price_war"
    rolled = random_action(chain, seed=4, week=2, opening_cost=6_000_000, wars={})
    again = random_action(chain, seed=4, week=2, opening_cost=6_000_000, wars={})
    assert rolled.kind == again.kind
    assert rolled.reason


def test_belief_decays_after_the_sample():
    from open_late.ai.memory import decay_belief

    memory = ActorMemory(actor_id="ceo:valuemax")
    memory.belief = {"price_fighter": 9.0, "passive": 1.0, "premium": 1.0, "expander": 1.0}
    decay_belief(memory, week=1)
    assert memory.belief["price_fighter"] == 9.0
    decay_belief(memory, week=27)
    assert memory.belief["price_fighter"] == pytest.approx(5.0)


def test_price_cutter_reaches_86_and_stops():
    from open_late.ai.constants import week_of
    from open_late.standin.sim import _player_step

    snap, provider = make_snapshot(2, difficulty="calm")
    for _ in range(28):
        _player_step(snap, provider, "price_cutter")
        snap.day += 7
        snap.week = week_of(snap.day)
    assert snap.public["player_price_index"]["evansville"] == 86
    assert all(row.get("city") != "houston" for row in snap.public["player_stores"])


def test_board_vetoes_a_big_call_that_breaks_the_floor():
    from open_late.ai.models import ChainPnL
    from open_late.ai.provider import _board_vetoes

    chain = RivalChain(
        chain_id="valuemax",
        personality_id="price_leader_v1",
        price_index=92,
        cash=100_000,
        stores=[],
    )
    chain.last_pnl = ChainPnL(week=1, sales=200_000, cogs=80_000, opex=80_000, net=40_000)
    action = Action(
        actor=ActorRef(kind="ceo", id="ceo:valuemax"),
        kind="raise_capital",
        args={"amount": 2_000_000},
        reason="ValueMax drew the shop line.",
    )
    assert _board_vetoes(chain, action) is False
    opening = Action(
        actor=ActorRef(kind="ceo", id="ceo:valuemax"),
        kind="open_store",
        args={"city": "houston", "cost": 19_640_000, "equity": 6_000_000, "loan": 13_640_000},
        reason="ValueMax filed to open a store in Houston.",
    )
    assert _board_vetoes(chain, opening) is True


def test_money_stays_integral_after_a_month():
    result = simulate(15, weeks=4, difficulty="standard", player_style="price_cutter")
    assert result.final_cash
    for cash in result.final_cash.values():
        assert isinstance(cash, int)
    assert CITIES[0] == "evansville"
