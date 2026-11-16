"""Rival chain chief executives.

One action per chain per week, chosen by the rules in ``rules.py``.
Year-ahead planning is only for opening or closing a store.
``advance_chain`` and ``follow_up_actions`` stay for a later reply.
"""

from __future__ import annotations

from open_late.ai.context import WeekContext
from open_late.ai.constants import (
    PRICE_INDEX_MAX,
    PRICE_INDEX_MIN,
)
from open_late.ai.forecast import _effects
from open_late.ai.legal import clamp_price
from open_late.ai.market import chain_sales, opened_store_id
from open_late.ai.models import Action, ActorMemory, BuildLoan, Personality, RivalChain, RivalStore
from open_late.ai.actors.rules import choose_by_rules


def advance_chain(chain: RivalChain, action: Action, opening_cost: int) -> RivalChain:
    """Chain after one action, so a follow-up is priced from that position."""
    shadow = chain.model_copy(deep=True)
    _price, _promo, _war, cut, cash, _count = _effects(shadow, action.kind, action.args, opening_cost)
    shadow.cash = cash
    shadow.cost_cut_pct = cut
    kind = action.kind
    args = action.args
    city = str(args.get("city", ""))
    if kind == "raise_capital":
        shadow.revolver_debt += int(args.get("amount", 0))
        shadow.refresh_debt()
    elif kind == "open_store":
        loan = int(args.get("loan", 0))
        if loan > 0:
            shadow.build_loans.append(BuildLoan(store_id="pending", original=loan, principal=loan))
            shadow.refresh_debt()
    elif kind == "pay_down_debt":
        pay = int(args.get("amount", 0))
        take = min(shadow.revolver_debt, pay)
        shadow.revolver_debt -= take
        left = pay - take
        for loan in shadow.build_loans:
            if left <= 0:
                break
            cut_principal = min(loan.principal, left)
            loan.principal -= cut_principal
            left -= cut_principal
        shadow.build_loans = [loan for loan in shadow.build_loans if loan.principal > 0]
        shadow.refresh_debt()
    elif kind == "set_chain_price_index":
        delta = int(args.get("delta", 0))
        shadow.price_index = clamp_price(shadow.price_index + delta)
        for store in shadow.stores:
            store.price_index = clamp_price(store.price_index + delta)
    elif kind == "defend":
        match = clamp_price(int(args.get("match_index", shadow.price_index)))
        shadow.price_index = match
        for store in shadow.stores:
            if not city or store.city == city:
                store.price_index = match
    elif kind == "start_price_war":
        cut_pts = int(args.get("intensity", 8)) // 2
        for store in shadow.stores:
            if not city or store.city == city:
                store.price_index = clamp_price(store.price_index - cut_pts)
        shadow.price_index = clamp_price(shadow.price_index - cut_pts)
    elif kind == "promo":
        depth = int(args.get("depth", 20))
        for store in shadow.stores:
            if store.status == "open" and (not city or store.city == city):
                store.promo_depth = depth
    elif kind == "open_store":
        existing = len([store for store in chain.stores if store.city == city])
        shadow.stores.append(
            RivalStore(
                id=str(args.get("store_id") or opened_store_id(chain.chain_id, city, existing)),
                city=city,
                opened_on=0,
                status="open",
                distance_band=int(args.get("site_band", 2)),
                price_index=shadow.price_index,
                focus_dept="grocery",
            )
        )
    elif kind == "close_store":
        sid = str(args.get("store_id", ""))
        for store in shadow.stores:
            if store.id == sid:
                store.status = "closed"
        if not any(store.status == "open" for store in shadow.stores):
            shadow.cash = 0
            shadow.revolver_debt = 0
            shadow.build_loans = []
            shadow.status = "bankrupt"
            shadow.ebitda_trail = []
            shadow.refresh_debt()
    elif kind == "cut_costs":
        shadow.cost_cut_pct = int(args.get("pct", cut))
    return shadow


def follow_up_actions(chain: RivalChain, first: Action) -> list[Action]:
    """Small second move kept for a reply. The weekly rules do not search it."""
    actor = first.actor
    rows = [Action(actor=actor, kind="do_nothing", args={})]
    for delta in (-4, 4):
        if PRICE_INDEX_MIN <= chain.price_index + delta <= PRICE_INDEX_MAX:
            rows.append(Action(actor=actor, kind="set_chain_price_index", args={"delta": delta}))
    city = str(first.args.get("city", ""))
    if not city:
        open_cities = [store.city for store in chain.stores if store.status == "open"]
        city = open_cities[0] if open_cities else ""
    has_door = any(store.status == "open" and (not city or store.city == city) for store in chain.stores)
    if has_door and city:
        rows.append(
            Action(actor=actor, kind="promo", args={"city": city, "dept": "grocery", "depth": 20, "weeks": 2})
        )
    if first.kind == "start_price_war" and city:
        rows.append(Action(actor=actor, kind="end_price_war", args={"city": city}))
    return rows


def _own_shift(market: list[dict], chain: RivalChain, city: str, segments: dict, income: dict) -> tuple[int, int]:
    """Sales dollars the new door takes from this chain, and the new door's own sales."""
    own = [row for row in market if row.get("city") == city and row.get("chain_id") == chain.chain_id]
    if not own:
        return 0, 0
    new = {
        "id": f"probe:{chain.chain_id}:{city}",
        "city": city,
        "owner": "rival",
        "chain_id": chain.chain_id,
        "price_index": chain.price_index,
        "distance_band": 2,
        "trust": 50,
        "promo": 0,
        "stockouts": 0,
    }
    before = chain_sales(market, chain.chain_id, segments, income, 0)
    after = chain_sales(list(market) + [new], chain.chain_id, segments, income, 0)
    stolen = sum(max(0, before.get(str(row["id"]), 0) - after.get(str(row["id"]), 0)) for row in own)
    return stolen, int(after.get(new["id"], 0))


def choose_ceo_action(
    chain: RivalChain,
    personality: Personality,
    memory: ActorMemory,
    *,
    seed: int,
    week: int,
    difficulty: str,
    opening_cost: int,
    wars: dict[str, int],
    player_price: dict[str, int],
    visit_mult: int = 1000,
    remodel_cost: int = 500_000,
    raise_amount: int = 2_000_000,
    market: list[dict] | None = None,
    segments: dict | None = None,
    income_by_city: dict[str, int] | None = None,
    factors: dict[str, int] | None = None,
    opening_costs: dict[str, int] | None = None,
    context: WeekContext | None = None,
) -> Action:
    """One legal weekly move. Big calls still pass through the caller's veto."""
    del seed, difficulty, opening_cost, player_price, visit_mult, remodel_cost, raise_amount
    if context is not None:
        factors = context.factors
        opening_costs = context.opening_costs
        market = context.market
        segments = context.segments
        income_by_city = context.income_by_city
    if chain.status == "bankrupt":
        action = Action(actor=ActorRef_safe(chain), kind="do_nothing", args={"rule": "none"})
        action.reason = f"{chain.chain_id} held because no rule fired."
        return action
    return choose_by_rules(
        chain,
        personality,
        memory,
        week=week,
        opening_costs=opening_costs,
        factors=factors,
        market=market,
        segments=segments,
        income_by_city=income_by_city,
        wars=wars,
    )


def ActorRef_safe(chain: RivalChain):
    from open_late.ai.models import ActorRef

    return ActorRef(kind="ceo", id=f"ceo:{chain.chain_id}")
