"""Patch E6: common-random-number difficulty and a short same-play check."""

from __future__ import annotations

import os

import pytest

from open_late.content import family_want_map, family_want_units
from open_late.economy import (
    CAP_MULT,
    DOWN_SKEW,
    EVENT_DURATION_MULT,
    EVENT_P_MULT,
    SIGMA_MULT,
    WALK_BIAS,
    difficulty_levers,
    economy_snapshot,
)
from open_late.engine import (
    answer,
    blocking,
    close_day,
    continue_morning,
    launch_campaign,
    new_game,
    place_capped_restock,
    set_assignment,
)
from open_late.finance import SIZE_MULT, starting_reserve
from open_late.hq import HOME_STORE_ID, store_pnl

LONG_TESTS = os.environ.get("RR_LONG_TESTS") == "1"
# Full 5-seed, 26-week basic+moderate sweep lives behind RR_LONG_TESTS=1.
SEEDS = (8, 15, 22, 31, 47)
DEFAULT_SEEDS = (8, 22, 47)
DEFAULT_WEEKS = 6
LONG_WEEKS = 26
HORIZON_WEEKS = DEFAULT_WEEKS
REST_RESERVE = 6_000 * SIZE_MULT
REST_CAP = 30_000 * SIZE_MULT


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
    dow = (state.day - 1) % 7
    for i, person in enumerate(team):
        want = "off" if dow == (i % 7) else "floor"
        if person.assignment != want:
            set_assignment(state, person.id, want)


def _build_basket(state) -> dict:
    basket: dict[str, dict[str, int]] = {}
    wants = family_want_map(state.products.values())
    for product in state.products.values():
        line = state.stock.get(product.id)
        on_hand = int(line.on_hand) if line is not None else 0
        on_order = int(getattr(line, "on_order", 0) or 0) if line is not None else 0
        want = wants.get(product.department) or family_want_units(product.department, state.products.values())
        need = want - on_hand - on_order
        if need <= 0:
            continue
        basket.setdefault(product.supplier_id, {})[product.id] = need
    return basket


def _restock(state) -> None:
    """Same Monday/Thursday fill and a fixed dollar cap on every tier."""
    if state.day % 7 not in (1, 4):
        return
    if state.cash <= REST_RESERVE:
        return
    cap = min(REST_CAP, max(0, state.cash - REST_RESERVE))
    place_capped_restock(state, _build_basket(state), cap, REST_RESERVE, ignore_minimum=True)


def play(state, weeks: int = HORIZON_WEEKS) -> dict:
    sales = 0
    contrib = 0
    for _ in range(weeks * 7):
        _restock(state)
        _staff_care(state)
        _close(state)
        if state.day % 7 == 0:
            pnl = store_pnl(state, HOME_STORE_ID, days=7)
            sales += int(pnl["sales"])
            contrib += int(pnl["contribution"])
        if state.failed:
            break
        continue_morning(state)
    return {
        "failed": state.failed,
        "reason": state.fail_reason,
        "cash": state.cash,
        "credit": int(state.credit_used),
        "sales": sales,
        "contrib": contrib,
        "margin": (contrib / sales) if sales else 0.0,
    }


def play_moderate(state, weeks: int = HORIZON_WEEKS) -> dict:
    """Ordinary E5 restock (Monday and Thursday fill) plus one cheap promo a month."""
    from tests.test_e5_yupper import _play as e5_play

    return e5_play(state, weeks, kind="moderate", promo=True)


def test_difficulty_levers_are_visible_and_ordered():
    """Sigma, event odds, caps, duration, walk bias, and downside skew are documented."""
    assert SIGMA_MULT["off"] == 0.0
    assert SIGMA_MULT["calm"] < SIGMA_MULT["standard"] < SIGMA_MULT["stern"]
    assert EVENT_P_MULT["off"] == 0.0
    assert EVENT_P_MULT["calm"] < EVENT_P_MULT["standard"] < EVENT_P_MULT["stern"]
    assert CAP_MULT["calm"] < CAP_MULT["standard"] <= CAP_MULT["stern"]
    assert EVENT_DURATION_MULT["calm"] <= EVENT_DURATION_MULT["standard"] <= EVENT_DURATION_MULT["stern"]
    assert WALK_BIAS["calm"] > WALK_BIAS["standard"] > WALK_BIAS["stern"]
    assert DOWN_SKEW["calm"] <= DOWN_SKEW["standard"] < DOWN_SKEW["stern"]
    for tier in ("calm", "standard", "stern"):
        row = difficulty_levers(tier)
        assert set(row) >= {
            "sigma_mult",
            "event_p_mult",
            "cap_mult",
            "event_duration_mult",
            "walk_bias",
            "down_skew",
            "starting_reserve",
        }
        snap = economy_snapshot(new_game("Harbor Ledger", "shop", seed=4, economy_difficulty=tier))
        assert snap["difficulty"] == tier
        assert snap["levers"] == difficulty_levers(tier)
        assert snap["levers"]["starting_reserve"] == starting_reserve("shop", tier)


def test_same_play_orders_tiers_on_cash_and_margin():
    """On identical restock and staffing, calm finishes at least as well as standard, then stern."""
    rows = {}
    for seed in DEFAULT_SEEDS:
        rows[seed] = {}
        for tier in ("calm", "standard", "stern"):
            state = new_game("Prairie Wire", "shop", seed=seed, economy_difficulty=tier)
            result = play(state, DEFAULT_WEEKS)
            rows[seed][tier] = result
            assert not result["failed"], f"seed {seed} {tier}: {result['reason']}"
        calm, mid, stern = rows[seed]["calm"], rows[seed]["standard"], rows[seed]["stern"]
        assert calm["cash"] >= mid["cash"] >= stern["cash"], (seed, {k: rows[seed][k]["cash"] for k in ("calm", "standard", "stern")})
        assert calm["margin"] >= mid["margin"] - 1e-9 >= stern["margin"] - 1e-9, (
            seed,
            {k: round(rows[seed][k]["margin"], 4) for k in ("calm", "standard", "stern")},
        )


def _in_band(margin: float, low: float, high: float) -> bool:
    return low - 1e-9 <= margin <= high + 1e-9


@pytest.mark.skipif(not LONG_TESTS, reason="set RR_LONG_TESTS=1 for the 26-week, 5-seed sweep")
def test_long_basic_and_moderate_hit_margin_bands():
    """26-week E7e bands after leftover-constant scale and WALK_BIAS retune.

    Basic targets: calm 3-5%, standard 2-4%, stern -1% to +1.5%, all solvent,
    cash and margin ordered calm >= standard >= stern. Moderate lift: at least
    13 of 15 seed-tier cells in +1.5 to +4.5 points, and no cell above +5.0.
    """
    basic = {}
    moderate = {}
    lifts: list[tuple[int, str, float]] = []
    for seed in SEEDS:
        basic[seed] = {}
        moderate[seed] = {}
        for tier in ("calm", "standard", "stern"):
            state = new_game("Prairie Wire", "shop", seed=seed, economy_difficulty=tier)
            basic[seed][tier] = play(state, LONG_WEEKS)
            state = new_game("Prairie Wire", "shop", seed=seed, economy_difficulty=tier)
            moderate[seed][tier] = play_moderate(state, LONG_WEEKS)
        b, m = basic[seed], moderate[seed]
        assert not b["calm"]["failed"] and not b["standard"]["failed"] and not b["stern"]["failed"]
        assert b["calm"]["cash"] >= b["standard"]["cash"] >= b["stern"]["cash"]
        assert b["calm"]["margin"] >= b["standard"]["margin"] - 1e-9 >= b["stern"]["margin"] - 1e-9
        assert _in_band(b["calm"]["margin"], 0.030, 0.050), (seed, b["calm"]["margin"])
        assert _in_band(b["standard"]["margin"], 0.020, 0.040), (seed, b["standard"]["margin"])
        assert _in_band(b["stern"]["margin"], -0.010, 0.015), (seed, b["stern"]["margin"])
        for tier in ("calm", "standard", "stern"):
            assert not m[tier]["failed"], (seed, tier, m[tier]["reason"])
            lift = m[tier]["margin"] - b[tier]["margin"]
            lifts.append((seed, tier, lift))
            assert lift <= 0.05 + 1e-9, (seed, tier, lift)
    in_band = sum(1 for _seed, _tier, lift in lifts if 0.015 - 1e-9 <= lift <= 0.045 + 1e-9)
    assert in_band >= 13, (in_band, [(s, t, round(v * 100, 2)) for s, t, v in lifts])
