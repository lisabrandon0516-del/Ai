"""Legal action menus.

The same rules decide what a mind may propose and what the stand-in will
accept. Argument ranges match the spec. A chain that cannot afford a store
does not get to open one.
"""

from __future__ import annotations

from open_late.ai.books import trailing_ebitda
from open_late.ai.constants import (
    BIG_CALL_COOLDOWN_WEEKS,
    BUILD_LTV,
    BUILD_TERM_WEEKS,
    BUILD_WEEKLY_RATE,
    CITIES,
    ENTRANT_CASH,
    ENTRANT_CREDIT_LINE,
    DEPARTMENTS,
    MIN_CASH_WEEKS,
    MIN_LIQUIDITY_WEEKS,
    NORTHLINE_BLOCKS_MIN,
    NORTHLINE_PRICE_MAX,
    NORTHLINE_PRICE_MIN,
    OPENING_COOLDOWN_WEEKS,
    PRICE_INDEX_MAX,
    PRICE_INDEX_MIN,
    WAR_COOLDOWN_WEEKS,
)
from open_late.ai.models import Action, ActorRef, RivalChain

PRICE_DELTAS: tuple[int, ...] = (-6, -4, -2, 2, 4, 6)
LOCAL_DELTAS: tuple[int, ...] = (-3, -1, 1, 3)
PROMO_DEPTHS: tuple[int, ...] = (10, 20, 30)


def _ready(chain: RivalChain, key: str, week: int) -> bool:
    return week >= int(chain.cooldowns.get(key, 0))


def funds(chain: RivalChain) -> int:
    """Cash plus the undrawn revolver. A building is not paid from this line."""
    room = max(0, chain.credit_line - chain.revolver_debt)
    return chain.cash + room


def last_store_cannot_earn(chain: RivalChain, next_13w_contribution: int) -> bool:
    """The only door may close when the last eight weeks and the next quarter both lose money."""
    trail = chain.ebitda_trail[-8:]
    if len(trail) < 8:
        return False
    return sum(trail) < 0 and next_13w_contribution < 0


def build_loan_terms(
    chain: RivalChain,
    cost: int,
    weekly_cost: int,
    incremental: int,
    ebitda_52: int | None = None,
) -> tuple[bool, int]:
    """Rules A, B, and C. Returns (allowed, loan).

    The loan is at most 70% of cost. The chain pays the rest in cash.
    """
    if cost <= 0 or weekly_cost < 0:
        return False, 0
    loan = int(cost * BUILD_LTV)
    equity = cost - loan
    cash_after = chain.cash - equity
    if cash_after < MIN_CASH_WEEKS * weekly_cost:
        return False, 0
    undrawn = max(0, chain.credit_line - chain.revolver_debt)
    if cash_after + undrawn < MIN_LIQUIDITY_WEEKS * weekly_cost:
        return False, 0
    ratio = chain.mandate.max_debt_ratio_x100 / 100.0
    base = trailing_ebitda(chain) if ebitda_52 is None else ebitda_52
    owed = chain.revolver_debt + loan + sum(item.principal for item in chain.build_loans)
    if base <= 0 or owed > ratio * base:
        return False, 0
    payment = int(round(loan * BUILD_WEEKLY_RATE)) + max(1, loan // BUILD_TERM_WEEKS)
    if incremental <= payment:
        return False, 0
    return True, loan


def entrant_door(
    chain: RivalChain,
    personality,
    factors: dict[str, int] | None,
    opening_costs: dict[str, int] | None,
) -> dict | None:
    """The first city that passes the same build rules, or nothing."""
    from open_late.ai.forecast import store_pnl
    from open_late.ai.models import RivalStore

    probe = chain.model_copy(deep=True)
    probe.cash = ENTRANT_CASH
    probe.revolver_debt = 0
    probe.build_loans = []
    probe.credit_line = ENTRANT_CREDIT_LINE
    probe.ebitda_trail = []
    probe.refresh_debt()
    for city in CITIES:
        cost = int((opening_costs or {}).get(city, 0))
        if cost <= 0:
            continue
        store = RivalStore(
            id=f"probe:{city}",
            city=city,
            opened_on=0,
            status="open",
            price_index=probe.price_index,
        )
        pnl = store_pnl(
            store,
            gross_margin_bps=personality.gross_margin_bps,
            opex_bps=personality.opex_bps,
            visit_mult=1000,
            war_intensity=0,
            cost_cut_pct=0,
            debt_share=0,
            factors=factors,
            shelf_index=personality.price_index,
        )
        # A new entrant has no history, so the debt cap uses the full-ramp forecast.
        allowed, loan = build_loan_terms(probe, cost, pnl.opex, pnl.net, max(0, pnl.net) * 52)
        if not allowed:
            continue
        return {"city": city, "cost": cost, "loan": loan, "equity": cost - loan}
    return None


def big_call_ready(chain: RivalChain, week: int) -> bool:
    return _ready(chain, "big_call", week)


def ceo_menu(
    chain: RivalChain,
    week: int,
    opening_cost: int,
    wars: dict[str, int],
    *,
    remodel_cost: int = 500_000,
    raise_amount: int = 2_000_000,
    paydown: int = 1_000_000,
    opening_costs: dict[str, int] | None = None,
    door_figures: dict[str, tuple[int, ...]] | None = None,
    ebitda_52: int | None = None,
    last_store_failing: bool = False,
) -> list[Action]:
    """Fixed menu. Infeasible rows are omitted so selection stays inside the rules."""
    actor = ActorRef(kind="ceo", id=f"ceo:{chain.chain_id}")
    if chain.status == "bankrupt":
        return []
    rows: list[Action] = []
    rows.append(Action(actor=actor, kind="do_nothing", args={}))
    for delta in PRICE_DELTAS:
        nxt = chain.price_index + delta
        if PRICE_INDEX_MIN <= nxt <= PRICE_INDEX_MAX:
            rows.append(Action(actor=actor, kind="set_chain_price_index", args={"delta": delta}))
    open_ok = _ready(chain, "opening", week) and big_call_ready(chain, week)
    # A door is on the menu only when equity, liquidity, leverage, and coverage all hold.
    open_now = [store for store in chain.stores if store.status == "open"]
    if open_ok and chain.cash >= 0 and door_figures:
        for city in CITIES:
            cost = int((opening_costs or {}).get(city, opening_cost))
            if cost <= 0 or city not in door_figures:
                continue
            row = door_figures[city]
            weekly_cost, incremental = int(row[0]), int(row[1])
            earned = int(row[2]) if len(row) > 2 else ebitda_52
            allowed, loan = build_loan_terms(chain, cost, weekly_cost, incremental, earned)
            if not allowed:
                continue
            rows.append(
                Action(
                    actor=actor,
                    kind="open_store",
                    args={"city": city, "site_band": 2, "cost": cost, "loan": loan, "equity": cost - loan},
                )
            )
    for store in chain.stores:
        if store.status != "open":
            continue
        if big_call_ready(chain, week) and (len(open_now) > 1 or (len(open_now) == 1 and last_store_failing)):
            rows.append(
                Action(
                    actor=actor,
                    kind="close_store",
                    args={"store_id": store.id, "city": store.city},
                )
            )
        if chain.cash >= remodel_cost:
            rows.append(
                Action(
                    actor=actor,
                    kind="remodel",
                    args={"store_id": store.id, "city": store.city, "cost": remodel_cost},
                )
            )
        if _ready(chain, f"war:{store.city}", week) and big_call_ready(chain, week):
            if wars.get(store.city, 0) == 0:
                rows.append(
                    Action(
                        actor=actor,
                        kind="start_price_war",
                        args={"city": store.city, "intensity": 8, "weeks": 4},
                    )
                )
        if wars.get(store.city, 0) > 0:
            rows.append(Action(actor=actor, kind="end_price_war", args={"city": store.city}))
        rows.append(
            Action(
                actor=actor,
                kind="promo",
                args={"city": store.city, "dept": "grocery", "depth": 20, "weeks": 2},
            )
        )
        rows.append(Action(actor=actor, kind="copy_best_seller", args={"city": store.city}))
        rows.append(Action(actor=actor, kind="defend", args={"city": store.city, "dept": "grocery"}))
    for pct in (1, 2, 3, 4):
        # A cut that is already in force is not a new decision.
        if pct <= chain.cost_cut_pct and week <= int(chain.cost_cut_until_week):
            continue
        rows.append(Action(actor=actor, kind="cut_costs", args={"pct": pct}))
    if big_call_ready(chain, week) and chain.revolver_debt + raise_amount <= chain.credit_line:
        owed = chain.refresh_debt() + raise_amount
        if len(chain.ebitda_trail) >= 13:
            base = trailing_ebitda(chain)
        else:
            base = max(0, chain.last_pnl.net) * 52
        cap = chain.mandate.max_debt_ratio_x100 / 100.0
        # The line is there for a week the drawer is already empty. A voluntary
        # draw, while cash is still positive, has to stay inside the debt cap.
        if chain.cash < 0 or (base > 0 and owed <= cap * base):
            rows.append(Action(actor=actor, kind="raise_capital", args={"amount": raise_amount}))
    # Extra cash pays the revolver down. The build loan amortises on its own.
    # The drawer keeps 13 weeks of operating cost (opex, rent and interest).
    weekly = chain.last_pnl.opex
    cushion = MIN_LIQUIDITY_WEEKS * weekly if weekly > 0 else 0
    if chain.revolver_debt > 0 and cushion > 0 and chain.cash > cushion:
        pay = min(chain.revolver_debt, chain.cash - cushion)
        if pay > 0:
            rows.append(Action(actor=actor, kind="pay_down_debt", args={"amount": pay}))
    return rows


def manager_menu(chain: RivalChain, store_id: str) -> list[Action]:
    store = next((item for item in chain.stores if item.id == store_id), None)
    actor = ActorRef(kind="store_manager", id=store_id)
    if store is None or store.status != "open" or chain.status == "bankrupt":
        return []
    rows = [Action(actor=actor, kind="hold", args={"store_id": store.id, "city": store.city})]
    for delta in LOCAL_DELTAS:
        rows.append(
            Action(
                actor=actor,
                kind="set_local_price",
                args={"store_id": store.id, "city": store.city, "delta": delta},
            )
        )
    for dept in DEPARTMENTS:
        rows.append(
            Action(
                actor=actor,
                kind="set_focus",
                args={"store_id": store.id, "city": store.city, "dept": dept},
            )
        )
    for level in ("lean", "normal", "heavy"):
        rows.append(
            Action(
                actor=actor,
                kind="set_staffing",
                args={"store_id": store.id, "city": store.city, "level": level},
            )
        )
    rows.append(
        Action(actor=actor, kind="request_promo", args={"store_id": store.id, "city": store.city})
    )
    rows.append(Action(actor=actor, kind="markdown", args={"store_id": store.id, "city": store.city}))
    return rows


def stamp_cooldowns(chain: RivalChain, action: Action, week: int) -> None:
    kind = action.kind
    if kind == "open_store":
        chain.cooldowns["opening"] = week + OPENING_COOLDOWN_WEEKS
        chain.cooldowns["big_call"] = week + BIG_CALL_COOLDOWN_WEEKS
    elif kind in {"close_store", "raise_capital"}:
        chain.cooldowns["big_call"] = week + BIG_CALL_COOLDOWN_WEEKS
    elif kind == "start_price_war":
        city = str(action.args.get("city", ""))
        chain.cooldowns[f"war:{city}"] = week + WAR_COOLDOWN_WEEKS
        chain.cooldowns["big_call"] = week + BIG_CALL_COOLDOWN_WEEKS


def clamp_price(value: int, low: int = PRICE_INDEX_MIN, high: int = PRICE_INDEX_MAX) -> int:
    return max(low, min(high, value))


def clamp_northline_price(value: int) -> int:
    return max(NORTHLINE_PRICE_MIN, min(NORTHLINE_PRICE_MAX, value))


def clamp_blocks(value: int) -> int:
    return max(NORTHLINE_BLOCKS_MIN, value)
