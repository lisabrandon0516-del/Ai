"""Smoke grid over seeds and difficulties. Long runs stay opt-in."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "retail_rivals"))

from open_late.standin.sim import simulate


def run_smoke() -> list[dict]:
    rows = []
    for seed in (1, 2):
        for difficulty in ("calm", "standard"):
            result = simulate(seed, weeks=4, difficulty=difficulty)
            rows.append(
                {
                    "seed": seed,
                    "difficulty": difficulty,
                    "reasons_ok": result.reasons_ok,
                    "chains": len(result.final_cash),
                    "nets": result.nets,
                }
            )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Retail Rivals AI smoke harness")
    parser.add_argument("--weeks", type=int, default=4)
    args = parser.parse_args()
    if args.weeks == 4:
        print(json.dumps(run_smoke(), indent=2))
        return
    result = simulate(1, weeks=args.weeks, difficulty="standard")
    print(json.dumps({"signature": result.signature, "reasons_ok": result.reasons_ok}))


if __name__ == "__main__":
    main()
