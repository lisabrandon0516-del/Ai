"""E8: hash-based economy-on RNG streams stay deterministic and independent."""

from __future__ import annotations

from open_late.economy import (
    _demand_salt,
    _event_rng,
    _linear_rng,
    _rng,
    demand_rng,
    stream_rng,
)
from open_late.engine import new_game
from tests.test_e6_yupper import play

# Frozen off-path baseline captured before the hash-scheme change (seed 8, 6 weeks).
OFF_SEED8_6W_CASH = 2_363_057
OFF_SEED8_6W_SALES = 8_968_459


def test_off_economy_keeps_linear_seeding_and_baseline():
    off = new_game("Prairie Wire", "shop", seed=8, economy_difficulty="off")
    # Linear alias still holds on the off path (intentional, bit-identical).
    assert _rng(off, 10, 100).random() == _rng(off, 9, 100 + 9_371).random()
    assert _rng(off, 10, 100).random() == _linear_rng(off, 10, 100).random()
    assert demand_rng(off, 10, "evansville", "grocery").random() == _linear_rng(
        off, 10, _demand_salt(off, "evansville", "grocery")
    ).random()
    result = play(new_game("Prairie Wire", "shop", seed=8, economy_difficulty="off"), 6)
    assert result["cash"] == OFF_SEED8_6W_CASH
    assert result["sales"] == OFF_SEED8_6W_SALES
    assert result["credit"] == 0
    assert not result["failed"]


def test_on_economy_breaks_linear_salt_aliases():
    state = new_game("Prairie Wire", "shop", seed=8, economy_difficulty="standard")
    a = _rng(state, 10, 100).random()
    b = _rng(state, 9, 100 + 9_371).random()
    assert a != b


def test_demand_streams_do_not_collide_with_factor_80_84_events():
    state = new_game("Prairie Wire", "shop", seed=8, economy_difficulty="standard")
    demand = [demand_rng(state, 10, "evansville", "grocery").random() for _ in range(3)]
    for factor_id in (80, 81, 82, 83, 84):
        event = [_event_rng(state, 10, factor_id).random() for _ in range(3)]
        assert demand != event, factor_id
        assert demand[0] != event[0], factor_id


def test_named_streams_with_different_names_are_independent():
    state = new_game("Prairie Wire", "shop", seed=8, economy_difficulty="standard")
    walk = stream_rng(state, "walk", 10, 0).random()
    demand = stream_rng(state, "demand", 10, "evansville", "grocery").random()
    event = stream_rng(state, "event", 10, 80, "", "").random()
    dc = stream_rng(state, "dc", 10, 0, 0).random()
    assert len({walk, demand, event, dc}) == 4


def test_same_seed_replays_identically_on_standard():
    def run():
        state = new_game("Prairie Wire", "shop", seed=22, economy_difficulty="standard")
        return play(state, 2)

    first = run()
    second = run()
    assert first["cash"] == second["cash"]
    assert first["sales"] == second["sales"]
    assert first["margin"] == second["margin"]
    assert first["failed"] == second["failed"]
