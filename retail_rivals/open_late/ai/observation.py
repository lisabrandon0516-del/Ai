"""What an actor is allowed to see.

O3 never leaves this function. O2 values get seeded noise. O0 and O1 are
copied as the caller supplied them (the caller is responsible for lagging O1).
"""

from __future__ import annotations

from typing import Any

from open_late.ai.constants import (
    CITIES,
    factor_key,
    parse_factor_key,
    tier_of,
)
from open_late.ai.models import ActorRef, MoneyRange, Observation
from open_late.ai.rng import ai_rng


def cash_band(cash: int, seed: int, week: int, chain_id: str, day: int) -> MoneyRange:
    """Coarse O2 band. Width is two $500k buckets, so the exact dollar is not shown."""
    from open_late.ai.constants import CASH_BAND_BUCKET

    bucket = CASH_BAND_BUCKET
    center = int(round(cash / bucket)) * bucket
    shift = ai_rng(seed, "ai.noise", week, chain_id, "cash_band").choice([-1, 0, 1])
    center += shift * bucket
    low = max(0, center - bucket)
    high = center + bucket
    return MoneyRange(low=low, high=high, as_of_day=day)


def build_observation(
    *,
    seed: int,
    week: int,
    day: int,
    actor: ActorRef,
    factors: dict[str, int],
    public: dict[str, Any],
    own: dict[str, Any],
    cities_with_channel: set[str],
) -> Observation:
    visible: dict[str, int] = {}
    tiers: dict[str, str] = {}
    for key in sorted(factors):
        factor_id, scope = parse_factor_key(key)
        tier = tier_of(factor_id)
        if tier == "O3":
            continue
        if tier == "O2" and not _o2_visible(actor, scope, cities_with_channel):
            continue
        value = int(factors[key])
        if tier == "O2":
            value = _noise_value(seed, week, actor.id, key, value)
        visible[key] = value
        tiers[key] = tier

    exposed = _public_for(actor, public, seed, week, cities_with_channel)
    return Observation(
        week=week,
        day=day,
        actor=actor,
        factors=visible,
        factor_tier=tiers,
        public=exposed,
        own=dict(own),
        noise_seed=f"{seed}|{week}|{actor.id}",
    )


def _o2_visible(actor: ActorRef, scope: str, cities_with_channel: set[str]) -> bool:
    if actor.kind == "northline":
        return True
    if actor.kind == "advisor":
        return True
    if not scope:
        return True
    if scope in CITIES:
        if actor.kind == "store_manager":
            return scope in cities_with_channel
        return scope in cities_with_channel or actor.kind in {"ceo", "town", "supplier"}
    return True


def _noise_value(seed: int, week: int, actor_id: str, key: str, value: int) -> int:
    draw = ai_rng(seed, "ai.noise", week, actor_id, key).gauss(0.0, 1.5)
    return int(round(value + draw))


def _public_for(
    actor: ActorRef,
    public: dict[str, Any],
    seed: int,
    week: int,
    cities_with_channel: set[str],
) -> dict[str, Any]:
    """Copy the public board. Price and sales pick up O2 noise for rivals."""
    exposed: dict[str, Any] = {}
    for key in sorted(public):
        if key in {"player_cash", "player_inventory", "player_orders", "player_deals", "player_staff"}:
            continue
        exposed[key] = public[key]

    if actor.kind == "advisor":
        return exposed

    prices = dict(public.get("player_price_index") or {})
    sales = dict(public.get("player_weekly_sales") or {})
    noisy_prices: dict[str, int] = {}
    for city in sorted(prices):
        if actor.kind == "store_manager" and city not in cities_with_channel:
            continue
        raw = int(prices[city])
        draw = ai_rng(seed, "ai.noise", week, actor.id, "price", city).gauss(0.0, 1.5)
        noisy_prices[city] = int(round(raw + draw))
    noisy_sales: dict[str, int] = {}
    store_cities = dict(public.get("player_store_cities") or {})
    for store_id in sorted(sales):
        city = store_cities.get(store_id, "")
        if actor.kind == "store_manager" and city not in cities_with_channel:
            continue
        raw = int(sales[store_id])
        sigma = max(1.0, abs(raw) * 0.12)
        draw = ai_rng(seed, "ai.noise", week, actor.id, "sales", store_id).gauss(0.0, sigma)
        noisy_sales[store_id] = max(0, int(round(raw + draw)))
    exposed["player_price_index"] = noisy_prices
    exposed["player_weekly_sales"] = noisy_sales
    return exposed


def empty_observation(actor: ActorRef, day: int, week: int) -> Observation:
    return Observation(
        week=week,
        day=day,
        actor=actor,
        factors={},
        factor_tier={},
        public={},
        own={},
        noise_seed="",
    )


def national_factors(level: int = 100) -> dict[str, int]:
    """A flat factor board, useful for tests and the stand-in."""
    board: dict[str, int] = {}
    for fid in range(1, 121):
        board[factor_key(fid)] = level
    return board
