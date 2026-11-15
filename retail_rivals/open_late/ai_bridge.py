"""Read-only door between the rival minds and the game.

No decisions live here. The minds import this module and nothing else
under ``open_late`` outside ``open_late.ai``.
"""

from __future__ import annotations

from dataclasses import dataclass

from open_late.corporate import MARKETS
from open_late.economy import SALES_CAP, _cap_mult, _key, _starting_values
from open_late.economy_e3 import LABOR_CAP, RENT_CAP

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
    """Rival build cost. WI-1 points this at the shared supercenter table."""
    from open_late.ai.costs import city_opening_cost

    return city_opening_cost(city, factors)
