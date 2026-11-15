"""Read-only door between the rival minds and the game.

No decisions live here. The minds import this module and nothing else
under ``open_late`` outside ``open_late.ai``.
"""

from __future__ import annotations

from dataclasses import dataclass

from open_late.corporate import MARKETS
from open_late.economy import SALES_CAP, _cap_mult, _key, _starting_values
from open_late.economy_e3 import LABOR_CAP, RENT_CAP
from open_late.store_costs import SUPERCENTER_BUILD_COST

API_VERSION = 1

# Canonical city order, the same order the market table is declared in.
CITIES: tuple[str, ...] = tuple(MARKETS)


def factor_key(fid: int, city: str | None = None) -> str:
    return _key(fid, city)


def starting_factors() -> dict[str, int]:
    return _starting_values()


def cap_mult(raw: float, cap: float) -> float:
    return _cap_mult(raw, cap)


@dataclass(frozen=True)
class MarketRow:
    id: str
    city: str
    rent_weekly: int
    build_cost: int
    min_cash_after: int
    build_days: int
    sales_tax_bps: int


def market_table() -> dict[str, MarketRow]:
    return {
        key: MarketRow(
            id=market.id,
            city=key,
            rent_weekly=market.rent_weekly,
            build_cost=market.opening_cost,
            min_cash_after=market.min_cash_after,
            build_days=market.build_days,
            sales_tax_bps=market.sales_tax_bps,
        )
        for key, market in MARKETS.items()
    }


def opening_cost(city: str, factors: dict[str, int] | None = None) -> int:
    """Shared supercenter cost times factor 95, clamped the way the engine clamps it."""
    base = SUPERCENTER_BUILD_COST[city]
    raw = 100
    if factors:
        raw = int(factors.get(factor_key(95, city), factors.get("95", 100)))
    mult = max(0.9, min(1.4, raw / 100.0))
    return int(round(base * mult))
