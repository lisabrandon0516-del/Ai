"""City markets the shopper card and the CEO forecast both read.

A market row is a public store: price, distance, trust, promo, stockouts,
focus, owner, and chain id. Player cash is not a field on these rows.
"""

from __future__ import annotations

from open_late.ai.constants import BASE_WEEKLY_SALES
from open_late.ai.legal import clamp_price
from open_late.ai.models import RivalChain
from open_late.ai.shoppers import choice_shares, visit_multipliers


def card_units(visit_mult: int, shock_bps: int) -> int:
    """Dollar sales from a logit multiplier. Price is already inside the multiplier."""
    shock = 1.0 + shock_bps / 10_000.0
    raw = BASE_WEEKLY_SALES * (max(0, visit_mult) / 1000.0) * shock
    return max(0, int(round(raw)))


def opened_store_id(chain_id: str, city: str, existing: int) -> str:
    return f"store:{chain_id}:{city}:{existing + 1}"


def apply_player_reply(market: list[dict], player_type: str | None, city: str = "") -> list[dict]:
    """How each player type answers, using only public prices and store lists.

    A price fighter undercuts the cheapest rival by 4. A premium player
    raises. An expander opens in the city the chain just moved on. Passive holds.
    """
    rows = [dict(row) for row in market]
    if player_type in {None, "", "passive"}:
        return rows
    if player_type == "expander":
        target = city or next(
            (str(row.get("city")) for row in rows if row.get("owner") == "player" and row.get("city")),
            "",
        )
        if target and not any(row.get("owner") == "player" and row.get("city") == target for row in rows):
            rows.append(
                {
                    "id": f"player:{target}",
                    "city": target,
                    "owner": "player",
                    "chain_id": "player",
                    "price_index": 100,
                    "distance_band": 1,
                    "trust": 60,
                    "promo": 0,
                    "stockouts": 0,
                    "focus": "grocery",
                }
            )
        return rows
    if player_type == "price_fighter":
        rival_prices = [int(row.get("price_index", 100)) for row in rows if row.get("owner") == "rival"]
        floor = (min(rival_prices) - 4) if rival_prices else 96
        for row in rows:
            if row.get("owner") != "player":
                continue
            row["price_index"] = clamp_price(min(int(row.get("price_index", 100)), floor))
        return rows
    if player_type == "premium":
        for row in rows:
            if row.get("owner") != "player":
                continue
            row["price_index"] = clamp_price(int(row.get("price_index", 100)) + 4)
        return rows
    return rows


def apply_chain_action(
    market: list[dict],
    chain: RivalChain,
    kind: str,
    args: dict | None = None,
    *,
    horizon: int = 13,
) -> list[dict]:
    """Public stores after this chain's action. Cash stays on the chain."""
    args = args or {}
    rows = [dict(row) for row in market]
    city = str(args.get("city", ""))
    ours = [row for row in rows if row.get("chain_id") == chain.chain_id]
    if kind == "set_chain_price_index":
        delta = int(args.get("delta", 0))
        for row in ours:
            row["price_index"] = clamp_price(int(row["price_index"]) + delta)
    elif kind == "defend":
        match = clamp_price(int(args.get("match_index", chain.price_index)))
        for row in ours:
            if not city or row.get("city") == city:
                row["price_index"] = match
    elif kind == "start_price_war":
        cut = int(args.get("intensity", 8)) // 2
        for row in ours:
            if not city or row.get("city") == city:
                row["price_index"] = clamp_price(int(row["price_index"]) - cut)
    elif kind == "markdown":
        for row in ours:
            if not city or row.get("city") == city:
                row["price_index"] = clamp_price(int(row["price_index"]) - 2)
    elif kind == "promo":
        depth = int(args.get("depth", 20))
        for row in ours:
            if not city or row.get("city") == city:
                row["promo"] = depth
    elif kind == "copy_best_seller":
        dept = str(args.get("dept", "grocery"))
        for row in ours:
            if not city or row.get("city") == city:
                row["focus"] = dept
    elif kind == "close_store":
        sid = str(args.get("store_id", ""))
        rows = [row for row in rows if row.get("id") != sid]
    elif kind == "open_store":
        existing = len([store for store in chain.stores if store.city == city])
        delay = int(args.get("delay_weeks", 4))
        ramp = max(0.0, horizon - delay) / max(1, horizon)
        rows.append(
            {
                "id": str(args.get("store_id") or opened_store_id(chain.chain_id, city, existing)),
                "city": city,
                "owner": "rival",
                "chain_id": chain.chain_id,
                "price_index": clamp_price(chain.price_index),
                "distance_band": int(args.get("site_band", 2)),
                "trust": 50,
                "promo": 0,
                "stockouts": 0,
                "focus": "grocery",
                "ramp": ramp,
            }
        )
    return rows


def _cities(market: list[dict], chain_id: str) -> list[str]:
    found = {str(row.get("city")) for row in market if row.get("chain_id") == chain_id and row.get("city")}
    return sorted(found)


def _local(market: list[dict], city: str) -> list[dict]:
    return [row for row in market if row.get("city") == city or row.get("id") == "online"]


def chain_sales(
    market: list[dict],
    chain_id: str,
    segments: dict,
    income_by_city: dict[str, int] | None,
    shock_bps: int,
) -> dict[str, int]:
    income_by_city = income_by_city or {}
    sales: dict[str, int] = {}
    for city in _cities(market, chain_id):
        local = _local(market, city)
        mults = visit_multipliers(local, segments, income_index=int(income_by_city.get(city, 100)))
        for row in local:
            if row.get("chain_id") != chain_id:
                continue
            units = card_units(mults.get(str(row["id"]), 0), shock_bps)
            units = int(round(units * max(1, int(row.get("price_index", 100))) / 100.0))
            ramp = float(row.get("ramp", 1.0))
            if ramp != 1.0:
                units = int(round(units * ramp))
            sales[str(row["id"])] = units
    return sales


def chain_share(
    market: list[dict],
    chain_id: str,
    segments: dict,
    income_by_city: dict[str, int] | None,
) -> float:
    """Sum of this chain's logit shares across the cities where it has a door."""
    income_by_city = income_by_city or {}
    total = 0.0
    for city in _cities(market, chain_id):
        local = _local(market, city)
        shares = choice_shares(local, segments, income_index=int(income_by_city.get(city, 100)))
        total += sum(shares.get(str(row["id"]), 0.0) for row in local if row.get("chain_id") == chain_id)
    return total
