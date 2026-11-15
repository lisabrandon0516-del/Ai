"""Plain snapshot the minds read.

The headquarters game is not in this repository. A future engine hook can
build this snapshot. The stand-in does that today. Player cash, stock, and
orders live on ``hidden`` and are not part of a rival observation.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from open_late.ai.models import AIState


class Snapshot(BaseModel):
    seed: int
    day: int = 1
    week: int = 1
    difficulty: str = "standard"
    ai_enabled: bool = True
    player_chain_id: str = "megamart"
    northline_smart: bool = False
    private_label: bool = False
    opening_cost: int = 6_000_000
    remodel_cost: int = 500_000
    raise_amount: int = 2_000_000
    factors: dict[str, int] = Field(default_factory=dict)
    public: dict[str, Any] = Field(default_factory=dict)
    wars: dict[str, int] = Field(default_factory=dict)
    accounts: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    northline: dict[str, Any] = Field(default_factory=dict)
    hidden: dict[str, Any] = Field(default_factory=dict)
    ai: AIState | None = None
