"""One read of the week, shared by every chain's search."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class WeekContext:
    week: int
    factors: dict[str, int]
    opening_costs: dict[str, int]
    income_by_city: dict[str, int]
    market: list[dict] = field(default_factory=list)
    segments: dict | None = None
