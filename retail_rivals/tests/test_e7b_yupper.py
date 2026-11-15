"""Patch E7b: hybrid traffic on the supercenter size pack."""

from __future__ import annotations

import time

from open_late.engine import (
    NAMED_BASKET_CAP,
    answer,
    blocking,
    close_day,
    continue_morning,
    new_game,
)
from open_late.finance import SIZE_MULT
from open_late.hq import HOME_STORE_ID, store_pnl


def _clear(state) -> None:
    for message in list(blocking(state)):
        for choice in message.choices:
            answer(state, message.id, choice.id)
            current = next(item for item in state.inbox if item.id == message.id)
            if current.resolved:
                break


def test_named_cap_and_size_mult_are_visible():
    assert SIZE_MULT == 15
    assert 300 <= NAMED_BASKET_CAP <= 500


def test_hybrid_week_hits_visit_and_sales_targets_and_closes_fast():
    """A standard door does ~3-6k visits/day and a $1-2M week, in well under 1s/day."""
    state = new_game("Harbor Ledger", "shop", seed=22, economy_difficulty="standard")
    visits = []
    times = []
    for i in range(7):
        _clear(state)
        t0 = time.perf_counter()
        assert close_day(state) == ""
        times.append(time.perf_counter() - t0)
        visits.append(state.history[-1].visits)
        if i < 6:
            continue_morning(state)
    avg = sum(visits) / 7
    assert min(visits) >= 2500
    assert max(visits) <= 7000
    assert 3000 <= avg <= 6000, (avg, visits)
    assert max(times) < 1.0, times
    pnl = store_pnl(state, HOME_STORE_ID, days=7)
    assert 1_000_000 <= int(pnl["sales"]) <= 2_000_000, pnl["sales"]
