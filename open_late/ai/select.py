"""Argmax with the spec tie-break, or a seeded softmax.

Tie-break order is move kind, then city, then store id. Softmax uses the
actor's own ``ai_rng`` stream. Temperature 0 is pure argmax.
"""

from __future__ import annotations

import math
import random

from open_late.ai.constants import CITY_ORDER, KIND_ORDER
from open_late.ai.models import Action


def _city_rank(action: Action) -> int:
    city = str(action.args.get("city", ""))
    return CITY_ORDER.get(city, 99)


def _store_rank(action: Action) -> str:
    return str(action.args.get("store_id", ""))


def tie_key(action: Action) -> tuple:
    return (
        KIND_ORDER.get(action.kind, 500),
        _city_rank(action),
        _store_rank(action),
        str(action.args.get("dept", "")),
        int(action.args.get("delta", 0)) if isinstance(action.args.get("delta", 0), int) else 0,
        action.kind,
    )


def argmax(scored: list[tuple[Action, float]]) -> Action:
    best_u = max(round(utility, 6) for _, utility in scored)
    tied = [action for action, utility in scored if round(utility, 6) == best_u]
    tied.sort(key=tie_key)
    return tied[0]


def softmax_pick(scored: list[tuple[Action, float]], rng: random.Random, temperature: float) -> Action:
    if temperature <= 0 or len(scored) == 1:
        return argmax(scored)
    ordered = sorted(scored, key=lambda item: tie_key(item[0]))
    utilities = [utility for _, utility in ordered]
    peak = max(utilities)
    weights = [math.exp((utility - peak) / temperature) for utility in utilities]
    total = sum(weights)
    draw = rng.random() * total
    cursor = 0.0
    for (action, _), weight in zip(ordered, weights):
        cursor += weight
        if draw <= cursor:
            return action
    return ordered[-1][0]
