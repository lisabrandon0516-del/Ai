"""Read the game's published cost and traffic coefficients.

Look-ahead does not fork the engine. It reads the factor dict the save
already holds and applies the same multipliers the game uses: factor 95 on
opening cost, factors 88 and 89 on rent, the visit terms from the week card,
and the labor terms that include the wage-floor event.
"""

from __future__ import annotations

from open_late.corporate import MARKETS
from open_late.economy import SALES_CAP, _cap_mult, _key, _starting_values
from open_late.economy_e3 import LABOR_CAP, RENT_CAP

# Event flags are 0 when the board has not stored them. Index factors are 100.
_FLAG_DEFAULT = {17: 0, 107: 0, 109: 0, 110: 0}


def game_factors() -> dict[str, int]:
    """The new-game factor card, including city keys and event flags."""
    return _starting_values()


def factor_value(factors: dict[str, int] | None, fid: int, city: str | None = None) -> int:
    board = factors or {}
    key = _key(fid, city)
    if key in board:
        return int(board[key])
    national = str(fid)
    if national in board:
        return int(board[national])
    return _FLAG_DEFAULT.get(fid, 100)


def opening_inflation(factors: dict[str, int] | None, city: str) -> float:
    """economy_e3.opening_cost_mult: clamp(factor 95 / 100, 0.9, 1.4)."""
    return max(0.9, min(1.4, factor_value(factors, 95, city) / 100.0))


def city_opening_cost(city: str, factors: dict[str, int] | None = None) -> int:
    """Sized market opening cost times build-out inflation. Evansville is 0."""
    market = MARKETS[city]
    if market.opening_cost <= 0:
        return 0
    return int(round(market.opening_cost * opening_inflation(factors, city)))


def opening_cost_table(factors: dict[str, int] | None = None) -> dict[str, int]:
    return {city: city_opening_cost(city, factors) for city in MARKETS}


def rent_multiplier(factors: dict[str, int] | None, city: str) -> float:
    """economy_e3.rent_mult without the sticky week. Cap is RENT_CAP."""
    raw = 100.0
    raw += (factor_value(factors, 88, city) - 100) * 0.70
    raw += (factor_value(factors, 89, city) - 100) * 0.40
    return _cap_mult(raw, RENT_CAP)


def weekly_rent(city: str, factors: dict[str, int] | None = None) -> int:
    return int(round(MARKETS[city].rent_weekly * rent_multiplier(factors, city)))


def traffic_mult(factors: dict[str, int] | None, city: str) -> float:
    """Week-card visit terms, then the road-work cut from apply_e3_visits."""
    visits = 100.0
    visits += (factor_value(factors, 8) - 100) * 0.35
    visits += (factor_value(factors, 11, city) - 100) * 1.00
    visits += (factor_value(factors, 2) - 100) * 0.25
    visits += (factor_value(factors, 21, city) - 100) * 0.20
    visits += (factor_value(factors, 5) - 100) * 0.20
    mult = visits / 100.0
    tour = factor_value(factors, 15, city) / 100.0
    access = factor_value(factors, 16, city) / 100.0
    mult *= (0.85 + 0.15 * tour) * (0.90 + 0.10 * access)
    if factor_value(factors, 17, city) >= 1:
        mult *= 0.92
    if SALES_CAP > 0:
        mult = _cap_mult(mult * 100.0, SALES_CAP)
    return mult


def labor_multiplier(factors: dict[str, int] | None, city: str) -> float:
    """economy_e3.labor_mult from the factor card. Wage-floor intensity is factor 107."""
    raw = 100.0
    raw += (factor_value(factors, 13, city) - 100) * 0.35
    raw += (factor_value(factors, 47, city) - 100) * 0.15
    raw += (factor_value(factors, 105) - 100) * 0.40
    raw += (factor_value(factors, 108, city) - 100) * 0.30
    intensity = factor_value(factors, 107, city)
    if intensity > 0:
        raw += intensity
    return _cap_mult(raw, LABOR_CAP)


def tax_drag_bps(factors: dict[str, int] | None, city: str) -> int:
    """Sales-tax dollars scale by factor 104. Neutral 100 adds nothing."""
    index = factor_value(factors, 104, city)
    return int(round(700 * (index / 100.0 - 1.0)))
