"""Section 4 acceptance harness.

Records the v4 baseline, the AI-off golden, and the decision golden.
Long runs stay behind an explicit flag so the default suite stays short.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "retail_rivals"))

from open_late.standin.sim import simulate  # noqa: E402

DATA = ROOT / "tests" / "data"
ARTIFACTS = ROOT / "artifacts"


def _load() -> tuple[float, float]:
    try:
        one, five, fifteen = os.getloadavg()
    except OSError:
        return 0.0, 0.0
    return one, fifteen


def decision_signature(seed: int, difficulty: str, weeks: int = 8) -> str:
    result = simulate(seed, weeks=weeks, difficulty=difficulty, player_style="passive")
    payload = result.signature.encode()
    return hashlib.sha256(payload).hexdigest()


def ai_off_signature(weeks: int = 26) -> str:
    result = simulate(1, weeks=weeks, difficulty="off", ai_enabled=True, player_style="passive")
    return hashlib.sha256(result.signature.encode()).hexdigest()


def record_goldens() -> dict:
    DATA.mkdir(parents=True, exist_ok=True)
    start, _ = _load()
    off = ai_off_signature()
    decisions = {}
    for difficulty in ("calm", "standard", "stern"):
        for seed in (1, 2, 3):
            decisions[f"{difficulty}:{seed}"] = decision_signature(seed, difficulty)
    end, _ = _load()
    payload = {
        "label": "v4",
        "commit": "cee2506",
        "ai_off_26w": off,
        "decision_8w": decisions,
        "load_start": start,
        "load_end": end,
    }
    (DATA / "v4_goldens.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def run_grid() -> list[dict]:
    rows = []
    for difficulty in ("calm", "standard", "stern"):
        for style in ("passive", "price_cutter", "expander"):
            for seed in (1, 2, 3):
                result = simulate(seed, weeks=52, difficulty=difficulty, player_style=style)
                rows.append(
                    {
                        "seed": seed,
                        "difficulty": difficulty,
                        "player_style": style,
                        "signature": hashlib.sha256(result.signature.encode()).hexdigest(),
                        "reasons_ok": result.reasons_ok,
                        "final_cash": result.final_cash,
                        "nets": result.nets,
                        "sales": result.sales,
                        "actions": result.actions,
                    }
                )
    return rows


def write_report(rows: list[dict], name: str) -> None:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    start, end = _load()
    body = {"load_start": start, "load_end": end, "runs": rows}
    (ARTIFACTS / f"{name}.json").write_text(json.dumps(body) + "\n", encoding="utf-8")
    lines = ["# Acceptance", "", f"Load {start:.2f} -> {end:.2f}", "", "| run | chains | reasons |", "|---|---|---|"]
    for row in rows:
        lines.append(
            f"| {row['difficulty']} {row['player_style']} seed {row['seed']} | {len(row['final_cash'])} | {row['reasons_ok']} |"
        )
    (ARTIFACTS / f"{name}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Retail Rivals acceptance harness")
    parser.add_argument("--goldens", action="store_true")
    parser.add_argument("--grid", action="store_true")
    parser.add_argument("--name", default="acceptance")
    args = parser.parse_args()
    if args.goldens:
        print(json.dumps(record_goldens(), indent=2))
    if args.grid:
        write_report(run_grid(), args.name)
        print(f"wrote artifacts/{args.name}.json")


if __name__ == "__main__":
    main()
