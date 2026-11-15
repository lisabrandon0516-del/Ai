"""Offline personality search. Not part of the default tests.

One generation. Each trial is rescored on the stand-in, which shares the
shopper logit across chains. Fitness is survival, ending rival share, and
how far apart the archetypes' action mixes are. Nothing is written unless
--out is passed.
"""

from __future__ import annotations

import argparse
import json

from open_late.ai.personalities import load_personalities
from open_late.ai.rng import ai_rng
from open_late.standin.sim import SimResult, simulate


def archetype_gap(groups: dict[str, list[str]]) -> float:
    """Mean pairwise distance between archetype action mixes. 0 is identical."""
    names = sorted(name for name, kinds in groups.items() if kinds)
    if len(names) < 2:
        return 0.0

    def hist(kinds: list[str]) -> dict[str, float]:
        counts: dict[str, int] = {}
        for kind in kinds:
            counts[kind] = counts.get(kind, 0) + 1
        total = len(kinds) or 1
        return {kind: count / total for kind, count in counts.items()}

    mixes = [hist(groups[name]) for name in names]
    total = 0.0
    pairs = 0
    for left in range(len(mixes)):
        for right in range(left + 1, len(mixes)):
            keys = set(mixes[left]) | set(mixes[right])
            distance = sum(abs(mixes[left].get(key, 0.0) - mixes[right].get(key, 0.0)) for key in keys)
            total += distance / 2.0
            pairs += 1
    return total / pairs if pairs else 0.0


def fitness_of(result: SimResult) -> float:
    alive = sum(1 for cash in result.final_cash.values() if cash > 0)
    rival = sum(result.sales.values())
    total = rival + result.player_sales
    share = (rival / total) if total else 0.0
    return alive + share + archetype_gap(result.kinds_by_archetype)


def evaluate(personalities: dict, *, seed: int, weeks: int) -> float:
    result = simulate(seed, weeks=weeks, difficulty="standard", personalities=personalities)
    return fitness_of(result)


def tune_generation(people: dict, *, seed: int, weeks: int) -> tuple[float, dict]:
    """Score the shipped weights, then one nudge per personality. Keep the best."""
    baseline = {key: person.model_copy(deep=True) for key, person in people.items()}
    best_score = evaluate(baseline, seed=seed, weeks=weeks)
    best = baseline
    rng = ai_rng(seed, "ai.tune", 0, "evolve")
    for person_id in sorted(people):
        trial = {key: person.model_copy(deep=True) for key, person in baseline.items()}
        weights = dict(trial[person_id].weights)
        name = sorted(weights)[rng.randrange(len(weights))]
        weights[name] = round(max(0.0, weights[name] + rng.choice([-0.1, 0.1])), 4)
        trial[person_id] = trial[person_id].model_copy(update={"weights": weights})
        score = evaluate(trial, seed=seed, weeks=weeks)
        if score >= best_score:
            best_score = score
            best = trial
    return best_score, best


def main() -> None:
    parser = argparse.ArgumentParser(description="Tune personality weights offline")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--weeks", type=int, default=52)
    parser.add_argument("--out", default="")
    args = parser.parse_args()
    people, digest = load_personalities()
    base = evaluate(people, seed=args.seed, weeks=args.weeks)
    best_score, best = tune_generation(people, seed=args.seed, weeks=args.weeks)
    print(json.dumps({"base_score": base, "best_score": best_score, "weeks": args.weeks, "weights_hash": digest}))
    if args.out:
        payload = {"version": 1, "personalities": [person.model_dump() for person in best.values()]}
        with open(args.out, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")


if __name__ == "__main__":
    main()
