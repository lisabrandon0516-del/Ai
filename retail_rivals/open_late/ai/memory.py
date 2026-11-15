"""Memory: grudges, beliefs, and the 26-row cap.

Updates are integer or dyadic so a save round-trip stays exact. Each tick is
guarded by the week number so a repeated Sunday call does not double-count.
"""

from __future__ import annotations

import random

from open_late.ai.constants import MEMORY_MOVES, PLAYER_TYPES
from open_late.ai.models import ActorMemory


def ensure_memory(memories: dict[str, ActorMemory], actor_id: str) -> ActorMemory:
    found = memories.get(actor_id)
    if found is None:
        found = ActorMemory(actor_id=actor_id, belief={name: 1.0 for name in PLAYER_TYPES})
        memories[actor_id] = found
    elif not found.belief:
        found.belief = {name: 1.0 for name in PLAYER_TYPES}
    return found


def belief_means(belief: dict[str, float]) -> dict[str, float]:
    alphas = {name: float(belief.get(name, 1.0)) for name in PLAYER_TYPES}
    total = sum(alphas.values()) or 1.0
    return {name: alphas[name] / total for name in PLAYER_TYPES}


def sample_player_type(rng: random.Random, means: dict[str, float]) -> str:
    """Draw a player type in PLAYER_TYPES order. One draw, no second stream."""
    roll = rng.random()
    cursor = 0.0
    chosen = PLAYER_TYPES[-1]
    for name in PLAYER_TYPES:
        cursor += float(means.get(name, 0.0))
        if roll <= cursor:
            return name
    return chosen


def update_belief(memory: ActorMemory, event_kind: str) -> None:
    alphas = memory.belief_or_prior()
    if event_kind == "price_cut":
        alphas["price_fighter"] += 1.0
    elif event_kind == "price_up":
        alphas["premium"] += 1.0
    elif event_kind == "opened":
        alphas["expander"] += 1.0
    else:
        alphas["passive"] += 0.25
    memory.belief = alphas


def decay_belief(memory: ActorMemory, week: int) -> None:
    """Pull the posterior toward the prior. Half of the evidence is gone after 26 weeks.

    Call this after the week's sample, so the week that saw the move still uses
    the undecayed posterior.
    """
    if memory.counters.get("belief_week") == week:
        return
    previous = int(memory.counters.get("belief_week", week))
    elapsed = max(0, week - previous)
    memory.counters["belief_week"] = week
    if elapsed <= 0 or not memory.belief:
        return
    keep = 0.5 ** (elapsed / 26.0)
    for name in memory.belief_or_prior():
        current = float(memory.belief.get(name, 1.0))
        memory.belief[name] = 1.0 + (current - 1.0) * keep


def decay_grudge(memory: ActorMemory, decay: int, week: int) -> None:
    if memory.counters.get("grudge_week") == week:
        return
    memory.grudge = max(0, min(100, memory.grudge - decay))
    memory.counters["grudge_week"] = week


def add_grudge(memory: ActorMemory, gain: int) -> None:
    memory.grudge = max(0, min(100, memory.grudge + gain))


def append_move(memory: ActorMemory, row: dict) -> None:
    memory.moves.append(row)
    if len(memory.moves) > MEMORY_MOVES:
        memory.moves = memory.moves[-MEMORY_MOVES:]


def recent_kinds(memory: ActorMemory, weeks: int, now: int) -> list[dict]:
    return [
        row
        for row in memory.moves
        if isinstance(row.get("week"), int) and now - int(row["week"]) < weeks and row.get("kind")
    ]
