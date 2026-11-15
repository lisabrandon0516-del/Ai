"""Debug-only explanation math.

Curves, combiner checks, and why-not sentences. Players never see this.
If a consideration breakdown is missing, the sentence says so.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Consideration:
    key: str
    label: str
    raw_input: float
    weight: float
    normalized_score: float
    contribution: float
    raw_unit: str = "index"
    curve_type: str = ""
    curve_params: dict[str, float] = field(default_factory=dict)


@dataclass
class CandidateView:
    label: str
    feasible: bool
    utility: float | None
    infeasible_reason: str = ""
    considerations: list[Consideration] = field(default_factory=list)

    @property
    def by_key(self) -> dict[str, Consideration]:
        return {item.key: item for item in self.considerations}


def eval_curve(curve_type: str, params: dict[str, float], raw: float) -> float | None:
    if curve_type == "identity":
        return raw
    if curve_type == "linear":
        x0 = params["x0"]
        x1 = params["x1"]
        y0 = params["y0"]
        y1 = params["y1"]
        if x1 == x0:
            t = 0.0
        else:
            t = (raw - x0) / (x1 - x0)
        t = min(1.0, max(0.0, t))
        return y0 + t * (y1 - y0)
    if curve_type == "inverse":
        flipped = params.get("x1", 1.0) - (raw - params.get("x0", 0.0))
        return eval_curve("linear", params, flipped)
    if curve_type == "step":
        threshold = params["threshold"]
        return params["y_hi"] if raw >= threshold else params["y_lo"]
    if curve_type == "threshold":
        if raw < params["lo"]:
            return 0.0
        if raw > params["hi"]:
            return params["y"]
        return params["y"]
    if curve_type == "logistic":
        import math

        k = params["k"]
        x_mid = params["x_mid"]
        y0 = params["y0"]
        y1 = params["y1"]
        try:
            s = 1.0 / (1.0 + math.exp(-k * (raw - x_mid)))
        except OverflowError:
            s = 0.0 if raw < x_mid else 1.0
        return y0 + s * (y1 - y0)
    return None


def combiner_matches(weight: float, normalized_score: float, contribution: float) -> bool:
    return abs(contribution - weight * normalized_score) <= 0.01


def why_not(
    chosen: CandidateView | None,
    other: CandidateView,
    *,
    tied: bool = False,
    tie_rule: str = "",
) -> str:
    if not other.feasible:
        return other.infeasible_reason or "Infeasible."
    if chosen is None:
        return "No action was chosen; every candidate was infeasible."
    if tied:
        rule = tie_rule or "move kind order, then city order, then store id"
        return f"Utilities tied. Tie-break: {rule}."
    if not other.considerations and (chosen is None or not chosen.considerations):
        left = "none" if chosen is None or chosen.utility is None else f"{chosen.utility:g}"
        right = "none" if other.utility is None else f"{other.utility:g}"
        return (
            f"Chosen utility {left} versus {right}. "
            "No consideration breakdown was recorded."
        )
    if not other.considerations:
        left = "none" if chosen.utility is None else f"{chosen.utility:g}"
        right = "none" if other.utility is None else f"{other.utility:g}"
        return (
            f"Chosen utility {left} versus {right}. "
            "No consideration breakdown was recorded."
        )

    keys = sorted(set(chosen.by_key) | set(other.by_key))
    ranked: list[tuple[float, str, float, float]] = []
    for key in keys:
        cv = chosen.by_key[key].contribution if key in chosen.by_key else 0.0
        ov = other.by_key[key].contribution if key in other.by_key else 0.0
        ranked.append((abs(cv - ov), key, cv, ov))
    ranked.sort(key=lambda row: (-row[0], row[1]))
    parts: list[str] = []
    for _delta, key, cv, ov in ranked[:3]:
        if cv == ov:
            continue
        favored = "the chosen move" if cv > ov else "this move"
        parts.append(f"{key} favored {favored} by {abs(cv - ov):g}")
    if not parts:
        return "The recorded considerations do not separate these moves."
    return "; ".join(parts) + "."
