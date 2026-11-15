"""Legal action menus.

The same rules decide what a mind may propose and what the stand-in will
accept. Argument ranges match the spec. A chain that cannot afford a store
does not get to open one.
"""

from __future__ import annotations

from open_late.ai.constants import (
    BIG_CALL_COOLDOWN_WEEKS,
    CITIES,
    DEPARTMENTS,
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
    room = max(0, chain.credit_line - chain.debt)
    return chain.cash + room


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
    if open_ok and funds(chain) >= opening_cost:
        for city in CITIES:
            here = [
                store
                for store in chain.stores
                if store.city == city and store.status in {"open", "building"}
            ]
            if len(here) >= 2:
                continue
            rows.append(
                Action(
                    actor=actor,
                    kind="open_store",
                    args={"city": city, "site_band": 2, "cost": opening_cost},
                )
            )
    for store in chain.stores:
        if store.status != "open":
            continue
        if big_call_ready(chain, week):
            rows.append(
                Action(
                    actor=actor,
                    kind="close_store",
                    args={"store_id": store.id, "city": store.city},
                )
            )
        if funds(chain) >= remodel_cost:
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
        rows.append(Action(actor=actor, kind="cut_costs", args={"pct": pct}))
    if big_call_ready(chain, week) and chain.debt + raise_amount <= chain.credit_line:
        rows.append(Action(actor=actor, kind="raise_capital", args={"amount": raise_amount}))
    if chain.debt > 0 and chain.cash >= paydown:
        pay = min(chain.debt, paydown)
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
