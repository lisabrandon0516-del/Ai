"""Save and action contracts.

Money fields are integer dollars. ``utility_terms`` may hold floats and is
never a player-facing surface. Names follow the engine side of the spec.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_serializer, model_validator

from open_late.ai.constants import PLAYER_TYPES, REASON_MAX


class ActorRef(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: str
    id: str


class Personality(BaseModel):
    id: str
    archetype: str
    weights: dict[str, float]
    grudge_gain: int
    grudge_decay: int
    temperature: float
    patience_quarters: int
    price_index: int
    gross_margin_bps: int
    opex_bps: int


class Mandate(BaseModel):
    """Board mandate.

    ``target_net_margin_bps`` is basis points (200 = 2%).
    ``growth_vs_profit`` is an integer 0–100 standing for the spec's 0–1,
    so a save stays exact.
    ``max_debt_ratio_x100`` is the debt/EBITDA cap times 100 (300 = 3.0x).
    """

    target_net_margin_bps: int = 200
    capex_budget: int = 12_000_000
    max_debt_ratio_x100: int = 300
    growth_vs_profit: int = 40


class ChainPnL(BaseModel):
    week: int = 0
    sales: int = 0
    cogs: int = 0
    opex: int = 0
    net: int = 0


class RivalStore(BaseModel):
    id: str
    city: str
    opened_on: int
    status: str = "building"
    distance_band: int = 2
    weekly_sales: int = 0
    focus_dept: str = "grocery"
    price_index: int = 100
    staffing: str = "normal"
    promo_depth: int = 0
    promo_until_week: int = 0


class BuildLoan(BaseModel):
    """A building's own loan. It is not the shop revolver."""

    store_id: str
    original: int
    principal: int
    rate_bps: int = 800
    term_weeks: int = 1040


class RivalChain(BaseModel):
    chain_id: str
    personality_id: str
    price_index: int
    cash: int
    revolver_debt: int = 0
    build_loans: list[BuildLoan] = Field(default_factory=list)
    # Sum of the revolver and the build loans. Old saves stored one number here.
    debt: int = 0
    credit_line: int = 10_000_000
    stores: list[RivalStore] = Field(default_factory=list)
    last_pnl: ChainPnL = Field(default_factory=ChainPnL)
    ebitda_trail: list[int] = Field(default_factory=list)
    status: str = "active"
    bankrupt_on: int | None = None
    cooldowns: dict[str, int] = Field(default_factory=dict)
    mandate: Mandate = Field(default_factory=Mandate)
    cost_cut_pct: int = 0
    cost_cut_until_week: int = 0

    @model_validator(mode="before")
    @classmethod
    def _migrate_one_debt_number(cls, data):
        if isinstance(data, dict) and "revolver_debt" not in data:
            data = dict(data)
            data["revolver_debt"] = int(data.get("debt") or 0)
            data["build_loans"] = data.get("build_loans") or []
        return data

    @model_validator(mode="after")
    def _sum_debt(self):
        self.debt = self.revolver_debt + sum(loan.principal for loan in self.build_loans)
        return self

    def refresh_debt(self) -> int:
        self.debt = self.revolver_debt + sum(loan.principal for loan in self.build_loans)
        return self.debt


class ActorMemory(BaseModel):
    actor_id: str
    grudge: int = 0
    belief: dict[str, float] = Field(default_factory=dict)
    ref_price: dict[str, int] = Field(default_factory=dict)
    habit: dict[str, float] = Field(default_factory=dict)
    moves: list[dict[str, Any]] = Field(default_factory=list)
    counters: dict[str, int] = Field(default_factory=dict)

    def belief_or_prior(self) -> dict[str, float]:
        if not self.belief:
            return {name: 1.0 for name in PLAYER_TYPES}
        return {name: float(self.belief.get(name, 1.0)) for name in PLAYER_TYPES}


class ShopperCard(BaseModel):
    week: int
    visit_mult: dict[str, int] = Field(default_factory=dict)
    dept_mult: dict[str, dict[str, int]] = Field(default_factory=dict)


class SupplierQuote(BaseModel):
    supplier_id: str
    cost_index: int = 100
    lead_time_days: int = 7
    allocation_bps: dict[str, int] = Field(default_factory=dict)
    terms_offer: dict[str, str] = Field(default_factory=dict)


class MoneyRange(BaseModel):
    low: int | None = None
    high: int | None = None
    as_of_day: int = 1


class Action(BaseModel):
    actor: ActorRef
    kind: str
    args: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""
    utility_terms: dict[str, float] = Field(default_factory=dict)

    @field_validator("reason")
    @classmethod
    def _reason_len(cls, value: str) -> str:
        if len(value) > REASON_MAX:
            raise ValueError(f"reason is {len(value)} characters; max is {REASON_MAX}")
        return value


class ActionResult(BaseModel):
    action: Action
    accepted: bool
    clamped: dict[str, Any] | None = None
    note: str = ""


class LogRow(BaseModel):
    """One applied week.

    The on-disk form stores the action once. ``ActionResult.action`` is the
    same object and is restored on load. A 26-week save has to stay under
    150 KB, and writing the action twice blows that cap at four chains.
    """

    day: int
    week: int
    action: Action
    result: ActionResult

    @model_validator(mode="before")
    @classmethod
    def _fill_result_action(cls, data):
        if isinstance(data, dict) and isinstance(data.get("result"), dict) and "action" not in data["result"]:
            if "action" in data:
                data = dict(data)
                data["result"] = dict(data["result"])
                data["result"]["action"] = data["action"]
        return data

    @model_serializer(mode="wrap")
    def _dump(self, handler):
        payload = handler(self)
        result = payload.get("result")
        if isinstance(result, dict):
            result.pop("action", None)
        action = payload.get("action")
        if isinstance(action, dict):
            # The live action still carries the score. The log does not,
            # or a 26-week stern save crosses the 150 KB cap.
            action.pop("utility_terms", None)
        return payload


class SourceRow(BaseModel):
    source_kind: str
    source_id: str
    outlet: str = ""
    observed_day: int
    heat_at_observation: int | None = None
    door_id: str = ""


class ConfidenceBlock(BaseModel):
    confidence: int | None
    band: str
    source_kind: str = "unknown"
    sources: list[SourceRow] = Field(default_factory=list)
    observed_day: int | None = None
    half_life_days: int = 14
    age_days: int = 0
    stale: bool = False
    corroboration_count: int = 0


class Recommendation(BaseModel):
    action_id: str
    label: str
    app_id: str
    supplier_id: str | None = None
    store_id: str | None = None
    actor: ActorRef | None = None
    department: str | None = None


class Advice(BaseModel):
    id: str
    day: int
    week: int
    headline: str
    body: str
    recommendation: Recommendation | None = None
    confidence: int | None = None
    band: str = "unknown"
    unread: bool = True


class Observation(BaseModel):
    week: int
    day: int
    actor: ActorRef
    factors: dict[str, int] = Field(default_factory=dict)
    factor_tier: dict[str, str] = Field(default_factory=dict)
    public: dict[str, Any] = Field(default_factory=dict)
    own: dict[str, Any] = Field(default_factory=dict)
    noise_seed: str = ""


class GameEvent(BaseModel):
    name: str
    day: int
    week: int
    store_id: str | None = None
    city: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class AIState(BaseModel):
    enabled: bool = False
    api_version: int = 1
    weights_hash: str = ""
    roster: list[str] = Field(default_factory=list)
    chains: dict[str, RivalChain] = Field(default_factory=dict)
    memories: dict[str, ActorMemory] = Field(default_factory=dict)
    supplier_quotes: dict[str, SupplierQuote] = Field(default_factory=dict)
    shopper_card: ShopperCard | None = None
    permits: dict[str, int] = Field(default_factory=dict)
    log: list[LogRow] = Field(default_factory=list)
    next_ids: dict[str, int] = Field(default_factory=dict)
    personalities: dict[str, Personality] = Field(default_factory=dict)


class Projection(BaseModel):
    sales: int
    contribution: int
    weekly_net: int
    share_change_bps: int
    cash_end: int
    p_cash_negative: float
    p10_contribution: int
    p90_contribution: int
