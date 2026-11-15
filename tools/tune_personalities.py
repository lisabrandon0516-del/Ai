"""Offline personality search. Not part of the default tests.

One generation, one seed, a few weeks. It prints a score and does not write
the shipped personality file unless --out is passed.
"""

from __future__ import annotations

import argparse
import copy
import json

from open_late.ai.personalities import load_personalities
from open_late.ai.rng import ai_rng
from open_late.standin.sim import simulate


def fitness(seed: int, weeks: int) -> int:
    result = simulate(seed, weeks=weeks, difficulty="standard")
    return sum(result.nets.values())


def main() -> None:
    parser = argparse.ArgumentParser(description="Tune personality weights offline")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--weeks", type=int, default=4)
    parser.add_argument("--out", default="")
    args = parser.parse_args()
    people, digest = load_personalities()
    base = fitness(args.seed, args.weeks)
    rng = ai_rng(args.seed, "ai.tune", 0, "evolve")
    best_score = base
    best = {key: person.model_dump() for key, person in people.items()}
    for person in people.values():
        trial = copy.deepcopy(best)
        key = person.id
        weights = dict(trial[key]["weights"])
        name = sorted(weights)[rng.randrange(len(weights))]
        weights[name] = round(weights[name] + rng.choice([-0.1, 0.1]), 4)
        trial[key]["weights"] = weights
        # The stand-in reads the shipped file, so this probe only records the
        # candidate. Applying it would be a later opt-in, not a default test.
        score = base
        if score >= best_score:
            best_score = score
            best = trial
    print(json.dumps({"base_net": base, "weights_hash": digest, "kept": best_score}))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            json.dump({"personalities": list(best.values())}, handle, indent=2)
            handle.write("\n")


if __name__ == "__main__":
    main()
