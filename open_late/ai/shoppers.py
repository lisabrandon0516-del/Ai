"""Shopper segments.

Six segments per city, baked on Sunday into integer multipliers (x1000).
Weekday code only looks the card up. When rivals are off, every multiplier
is exactly 1000 and this module draws no random numbers.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from open_late.ai.constants import CITIES, DEPARTMENTS, SEGMENTS
from open_late.ai.models import ShopperCard

_DATA = Path(__file__).resolve().parent / "data" / "segments_v1.json"


def load_segments(path: Path | None = None) -> dict[str, dict]:
    payload = json.loads((path or _DATA).read_text(encoding="utf-8"))
    return payload["segments"]


def segment_mix(income_index: int) -> dict[str, float]:
    tilt = max(-1.0, min(1.0, (income_index - 100) / 40.0))
    raw = {
        "value_stretchers": 0.22 - 0.08 * tilt,
        "busy_families": 0.24,
        "fresh_first": 0.14 + 0.06 * tilt,
        "brand_loyal": 0.12 + 0.08 * tilt,
        "deal_hunters": 0.16 - 0.06 * tilt,
        "online_leaners": 0.12,
    }
    total = sum(raw[name] for name in SEGMENTS)
    return {name: raw[name] / total for name in SEGMENTS}


def softmax(utilities: dict[str, float]) -> dict[str, float]:
    keys = sorted(utilities)
    if not keys:
        return {}
    peak = max(utilities[key] for key in keys)
    weights = {key: math.exp(utilities[key] - peak) for key in keys}
    total = sum(weights.values()) or 1.0
    return {key: weights[key] / total for key in keys}


def store_utility(coef: dict, store: dict, habit: float) -> float:
    utility = (
        float(coef["b_price"]) * (int(store["price_index"]) - 100)
        + float(coef["b_dist"]) * int(store["distance_band"])
        + float(coef["b_rep"]) * ((int(store["trust"]) - 50) / 50.0)
        + float(coef["b_promo"]) * (int(store.get("promo", 0)) / 100.0)
        + float(coef["b_stockout"]) * float(store.get("stockouts", 0))
        + float(coef["b_habit"]) * habit
    )
    if store.get("id") == "online":
        utility += float(coef.get("b_online", 0.0))
    return utility


def choice_shares(
    stores: list[dict],
    segments: dict[str, dict],
    *,
    income_index: int = 100,
    habit: dict[str, float] | None = None,
) -> dict[str, float]:
    """Segment-weighted choice shares, including an online option if present."""
    habit = habit or {}
    mix = segment_mix(income_index)
    totals = {str(store["id"]): 0.0 for store in stores}
    for name in SEGMENTS:
        coef = segments[name]
        utilities = {
            str(store["id"]): store_utility(coef, store, habit.get(str(store["id"]), 0.0))
            for store in stores
        }
        shares = softmax(utilities)
        weight = mix[name]
        for store_id, share in shares.items():
            totals[store_id] += weight * share
    return totals


def _identity(store_ids: list[str], week: int) -> ShopperCard:
    visit = {store_id: 1000 for store_id in sorted(store_ids)}
    dept = {store_id: {dept: 1000 for dept in DEPARTMENTS} for store_id in sorted(store_ids)}
    return ShopperCard(week=week, visit_mult=visit, dept_mult=dept)


def bake_card(
    *,
    week: int,
    enabled: bool,
    segments: dict[str, dict],
    stores: list[dict],
    income_by_city: dict[str, int],
    habit: dict[str, float] | None = None,
) -> ShopperCard:
    """Build the Sunday card.

    ``stores`` entries need id, city, owner (``player``, ``rival``, ``northline``,
    or ``online``), price_index, distance_band, trust, promo, stockouts, focus.
    """
    physical = [store for store in stores if store.get("owner") != "online"]
    if not enabled:
        return _identity([str(store["id"]) for store in physical], week)

    rival_alive = any(store.get("owner") in {"rival", "northline"} for store in physical)
    if not rival_alive:
        return _identity([str(store["id"]) for store in physical], week)

    habit = habit or {}
    visit: dict[str, int] = {}
    dept: dict[str, dict[str, int]] = {}
    for city in CITIES:
        city_stores = [store for store in stores if store.get("city") in {city, ""} or store.get("id") == "online"]
        local = [store for store in city_stores if store.get("city") == city or store.get("id") == "online"]
        if not any(store.get("owner") in {"rival", "northline"} for store in local):
            for store in local:
                if store.get("id") == "online":
                    continue
                visit[str(store["id"])] = 1000
                dept[str(store["id"])] = {name: 1000 for name in DEPARTMENTS}
            continue
        solo_stores = [store for store in local if store.get("owner") in {"player", "online"}]
        income = income_by_city.get(city, 100)
        full = choice_shares(local, segments, income_index=income, habit=habit)
        solo = choice_shares(solo_stores, segments, income_index=income, habit=habit) if solo_stores else {}
        player_solo = [share for sid, share in solo.items() if sid != "online"]
        anchor = sum(player_solo) / len(player_solo) if player_solo else 1.0
        anchor = anchor or 1.0
        for store in local:
            if store.get("id") == "online":
                continue
            sid = str(store["id"])
            if store.get("owner") == "player" and sid in solo and solo[sid] > 0:
                mult = int(round(1000 * full.get(sid, 0.0) / solo[sid]))
            else:
                mult = int(round(1000 * full.get(sid, 0.0) / anchor))
            visit[sid] = max(0, min(5000, mult))
            dept[sid] = _dept_mult(store, segments, income)
    return ShopperCard(week=week, visit_mult=visit, dept_mult=dept)


def _dept_mult(store: dict, segments: dict[str, dict], income: int) -> dict[str, int]:
    mix = segment_mix(income)
    focus = str(store.get("focus") or "")
    raw: dict[str, float] = {}
    for dept in DEPARTMENTS:
        pref = 0.0
        for name in SEGMENTS:
            pref += mix[name] * float(segments[name].get("depts", {}).get(dept, 1.0))
        if dept == focus:
            pref *= 1.2
        raw[dept] = pref
    mean = sum(raw.values()) / len(DEPARTMENTS)
    mean = mean or 1.0
    return {dept: max(200, min(3000, int(round(1000 * raw[dept] / mean)))) for dept in DEPARTMENTS}


def visit_share_mult(card: ShopperCard | None, store_id: str) -> float:
    if card is None:
        return 1.0
    return card.visit_mult.get(store_id, 1000) / 1000.0


def dept_weight_mult(card: ShopperCard | None, store_id: str, dept: str) -> float:
    if card is None:
        return 1.0
    return card.dept_mult.get(store_id, {}).get(dept, 1000) / 1000.0
