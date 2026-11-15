"""Boards, store managers, suppliers, towns, and the optional Northline mind."""

from __future__ import annotations

from open_late.ai.constants import (
    CITIES,
    NORTHLINE_PRICE_MAX,
    NORTHLINE_PRICE_MIN,
    SUPPLIER_NAMES,
    week_of,
)
from open_late.ai.legal import clamp_blocks, clamp_northline_price, manager_menu
from open_late.ai.models import Action, ActorMemory, ActorRef, Personality, RivalChain, SupplierQuote
from open_late.ai.reasons import board_reason, manager_reason, northline_reason, supplier_reason, town_reason
from open_late.ai.rng import ai_rng
from open_late.ai.select import argmax

_CYCLE = ["price_leader", "premium", "expander"]


def board_actions(
    chain: RivalChain,
    memory: ActorMemory,
    personality: Personality,
    *,
    seed: int,
    week: int,
    personalities: dict[str, Personality],
    factors: dict[str, int] | None = None,
    opening_costs: dict[str, int] | None = None,
) -> list[Action]:
    actor = ActorRef(kind="board", id=f"board:{chain.chain_id}")
    if chain.status == "bankrupt":
        locked = chain.bankrupt_on is None or week < week_of(chain.bankrupt_on) + 52
        if locked:
            return []
        from open_late.ai.legal import entrant_door

        offer = entrant_door(chain, personality, factors, opening_costs)
        if offer is None:
            return []
        memory.counters["filed"] = 0
        memory.counters["declared"] = 0
        memory.counters["weeks_cash_negative"] = 0
        memory.counters["weeks_distressed"] = 0
        return [_board(actor, chain, "reenter", offer)]
    if memory.counters.get("cash_week") != week:
        if chain.cash < 0:
            memory.counters["weeks_cash_negative"] = memory.counters.get("weeks_cash_negative", 0) + 1
        else:
            memory.counters["weeks_cash_negative"] = 0
        if chain.status == "distressed" and chain.cash < 0:
            memory.counters["weeks_distressed"] = memory.counters.get("weeks_distressed", 0) + 1
        elif chain.cash >= 0:
            memory.counters["weeks_distressed"] = 0
        memory.counters["cash_week"] = week

    actions: list[Action] = []
    negative = memory.counters.get("weeks_cash_negative", 0)
    distressed = memory.counters.get("weeks_distressed", 0)
    if chain.status == "active" and negative >= 4 and memory.counters.get("declared") != 1:
        actions.append(_board(actor, chain, "declare_distress", {}))
        memory.counters["declared"] = 1
    if (
        chain.status == "distressed"
        and distressed >= 8
        and chain.cash < 0
        and memory.counters.get("filed") != 1
    ):
        actions.append(_board(actor, chain, "file_bankruptcy", {}))
        memory.counters["filed"] = 1

    quarter = week > 0 and week % 13 == 0
    if not quarter and not actions:
        return actions

    if quarter:
        growth = {"price_leader": 35, "premium": 20, "expander": 80}.get(personality.archetype, 40)
        mandate = {
            "target_net_margin_bps": 200,
            "capex_budget": chain.mandate.capex_budget,
            "max_debt_ratio_x100": chain.mandate.max_debt_ratio_x100,
            "growth_vs_profit": growth,
            "restore_active": 1 if chain.status == "distressed" and chain.cash >= 0 else 0,
        }
        actions.append(_board(actor, chain, "set_mandate", mandate))
        sales = chain.last_pnl.sales
        margin_bps = int(round(chain.last_pnl.net / sales * 10_000)) if sales else 0
        target = chain.mandate.target_net_margin_bps
        if margin_bps < target:
            memory.counters["quarters_under"] = memory.counters.get("quarters_under", 0) + 1
        else:
            memory.counters["quarters_under"] = 0
        under = memory.counters.get("quarters_under", 0)
        if under >= personality.patience_quarters:
            memory.counters["quarters_under"] = 0
            current = personality.archetype if personality.archetype in _CYCLE else "price_leader"
            options = [name for name in _CYCLE if name != current]
            pick = options[ai_rng(seed, "ai.board", week, chain.chain_id, "replace").randrange(len(options))]
            replacement = _personality_id(personalities, pick)
            actions.append(
                _board(actor, chain, "replace_ceo", {"personality_id": replacement, "archetype": pick})
            )
    return actions


def _personality_id(personalities: dict[str, Personality], archetype: str) -> str:
    ids = sorted(person.id for person in personalities.values() if person.archetype == archetype)
    if ids:
        return ids[0]
    fallback = sorted(personalities)
    return fallback[0] if fallback else f"{archetype}_v1"


def _board(actor: ActorRef, chain: RivalChain, kind: str, args: dict) -> Action:
    action = Action(actor=actor, kind=kind, args=args, reason=board_reason(chain.chain_id, kind))
    return action


def choose_manager_action(
    chain: RivalChain,
    store_id: str,
    *,
    player_index: int,
    week: int,
) -> Action | None:
    menu = manager_menu(chain, store_id)
    if not menu:
        return None
    store = next(item for item in chain.stores if item.id == store_id)
    gap = store.price_index - player_index

    def score(action: Action) -> float:
        if action.kind == "set_local_price":
            if abs(gap) < 3:
                return -1.0
            delta = int(action.args["delta"])
            return abs(gap) - abs(gap + delta)
        if action.kind == "markdown" and store.price_index > chain.price_index + 2:
            return 0.4
        if action.kind == "set_focus" and gap >= 3 and action.args.get("dept") == "grocery":
            return 0.15
        if action.kind == "set_staffing" and action.args.get("level") == "lean" and chain.cash < 2_000_000:
            return 0.25
        if action.kind == "set_staffing" and action.args.get("level") == store.staffing:
            return 0.05
        if action.kind == "hold":
            return 0.0
        return -0.05

    scored = [(action, score(action)) for action in menu]
    # Stable: higher score, then the menu order via kind/dept already in argmax tie-break.
    chosen = argmax(scored)
    chosen.reason = manager_reason(chain.chain_id, store.city, chosen.kind if chosen.kind != "hold" else "hold")
    if chosen.kind == "hold":
        chosen.reason = manager_reason(chain.chain_id, store.city, "hold")
    chosen.utility_terms = {"local": round(score(chosen), 6)}
    return chosen


def supplier_actions(
    supplier_id: str,
    quote: SupplierQuote,
    accounts: list[dict],
    *,
    commodity_index: int,
    shortage: bool,
    slip_index: int,
    week: int,
    hidden: bool,
) -> list[Action]:
    if hidden:
        return []
    name = SUPPLIER_NAMES.get(supplier_id, supplier_id)
    actor = ActorRef(kind="supplier", id=f"supplier:{supplier_id}")
    actions: list[Action] = []
    gap = int(commodity_index) - quote.cost_index
    step = max(-2, min(2, gap))
    if step != 0:
        actions.append(
            Action(
                actor=actor,
                kind="adjust_cost",
                args={"cost_index": quote.cost_index + step},
                reason=supplier_reason(name, "adjust_cost"),
                utility_terms={"step": float(step)},
            )
        )
    if shortage and accounts:
        weights = {
            str(row["buyer_id"]): max(1, int(row.get("relationship", 1))) * max(1, int(row.get("volume", 1)))
            for row in accounts
        }
        allocation = _allocate(weights)
        actions.append(
            Action(
                actor=actor,
                kind="allocate",
                args={"allocation_bps": allocation},
                reason=supplier_reason(name, "allocate"),
            )
        )
    lead = 7 + max(0, (int(slip_index) - 100) // 10)
    if lead != quote.lead_time_days:
        actions.append(
            Action(
                actor=actor,
                kind="quote_lead_time",
                args={"lead_time_days": lead},
                reason=supplier_reason(name, "quote_lead_time"),
            )
        )
    if week % 4 == 1 and accounts:
        offers = {
            str(row["buyer_id"]): terms_for(int(row.get("relationship", 0)), int(row.get("volume", 0)))
            for row in sorted(accounts, key=lambda item: str(item["buyer_id"]))
        }
        if offers != quote.terms_offer:
            actions.append(
                Action(
                    actor=actor,
                    kind="offer_terms",
                    args={"terms_offer": offers},
                    reason=supplier_reason(name, "offer_terms"),
                )
            )
    return actions


def terms_for(relationship: int, volume: int) -> str:
    """Same ladder for every buyer. Net 14 needs relationship of at least 55."""
    if relationship >= 70 and volume >= 1200:
        return "net30"
    if relationship >= 55:
        return "net14"
    return "cash"


def _allocate(weights: dict[str, int]) -> dict[str, int]:
    keys = sorted(weights)
    if not keys:
        return {}
    total = sum(weights[key] for key in keys)
    if total <= 0:
        base = 10000 // len(keys)
        out = {key: base for key in keys}
        for key in keys[: 10000 - base * len(keys)]:
            out[key] += 1
        return out
    raw = {key: 10000 * weights[key] / total for key in keys}
    out = {key: int(raw[key]) for key in keys}  # floor toward 0 for positive
    remainder = 10000 - sum(out.values())
    order = sorted(keys, key=lambda key: (-(raw[key] - out[key]), key))
    for key in order[:remainder]:
        out[key] += 1
    return out


def town_actions(
    *,
    seed: int,
    week: int,
    day: int,
    permits: list[dict],
    factors: dict[str, int],
    doors: dict[str, int] | None = None,
) -> list[Action]:
    actions: list[Action] = []
    for permit in sorted(permits, key=lambda row: (str(row.get("city", "")), str(row.get("applicant", "")))):
        city = str(permit.get("city", ""))
        applicant = str(permit.get("applicant", ""))
        delay = 2 + ai_rng(seed, "ai.town", week, applicant, city, "delay").randrange(7)
        actor = ActorRef(kind="town", id=f"town:{city}")
        actions.append(
            Action(
                actor=actor,
                kind="permit",
                args={"city": city, "applicant": applicant, "result": "delay", "weeks": delay},
                reason=town_reason(city, "permit", delay),
            )
        )
    if week > 0 and week % 4 == 0:
        counts = doors or {}
        for city in CITIES:
            actions.extend(_local_rules(seed, week, city, factors, int(counts.get(city, 0))))
    return actions


_FLAG_FACTORS = (17, 107, 109, 110)


def _flag_on(factors: dict[str, int], fid: int, city: str) -> bool:
    return int(factors.get(f"{fid}:{city}", factors.get(str(fid), 0))) != 0


def _local_rules(seed: int, week: int, city: str, factors: dict[str, int], doors: int) -> list[Action]:
    """One local rule, and any flag that is on turns off unless it is being set now.

    A flag stays up for a month. The next town week clears it, so road work and
    inspections do not stick for the rest of the year. Sales tax steps once a quarter.
    """
    income = int(factors.get(f"14:{city}", factors.get("14", 100)))
    if doors >= 4:
        fid, kind, mode = 17, "schedule_road_work", "flag"
    elif doors >= 2:
        fid, kind, mode = 109, "schedule_inspection", "flag"
    elif income >= 108:
        wage = int(factors.get(f"107:{city}", factors.get("107", 0)))
        if wage <= 0:
            fid, kind, mode = 107, "propose_wage_floor", "intensity"
        else:
            fid, kind, mode = 108, "set_fair_schedule", "walk"
    elif income <= 97:
        fid, kind, mode = 110, "set_bag_rule", "flag"
    else:
        fid, kind, mode = 104, "sales_tax_drift", "walk"
    step = 1 + ai_rng(seed, "ai.town", week, city, "rule").randrange(2)
    actor = ActorRef(kind="town", id=f"town:{city}")
    actions: list[Action] = []
    setting = fid if mode in {"flag", "intensity"} and not _flag_on(factors, fid, city) else None
    if setting == 17 or setting == 109 or setting == 110:
        actions.append(
            Action(
                actor=actor,
                kind=kind,
                args={"factor_id": fid, "value": 1, "cities": [city]},
                reason=town_reason(city, kind),
            )
        )
    elif setting == 107:
        actions.append(
            Action(
                actor=actor,
                kind=kind,
                args={"factor_id": fid, "value": 2 + step, "cities": [city]},
                reason=town_reason(city, kind),
            )
        )
    elif mode == "walk" and week % 12 == 0:
        current = int(factors.get(f"{fid}:{city}", factors.get(str(fid), 100)))
        actions.append(
            Action(
                actor=actor,
                kind=kind,
                args={"factor_id": fid, "delta": step if current < 106 else -step, "cities": [city]},
                reason=town_reason(city, kind),
            )
        )
    for other in _FLAG_FACTORS:
        if other == setting or not _flag_on(factors, other, city):
            continue
        actions.append(
            Action(
                actor=actor,
                kind="clear_rule",
                args={"factor_id": other, "value": 0, "cities": [city]},
                reason=town_reason(city, "clear_rule"),
            )
        )
    return actions


def choose_northline(
    northline: dict,
    *,
    player_index: int,
    seed: int,
    week: int,
) -> Action:
    actor = ActorRef(kind="northline", id="northline")
    price = int(northline.get("price_index", 102))
    blocks = int(northline.get("blocks_away", 8))
    reputation = int(northline.get("reputation", 38))
    menu: list[tuple[Action, float]] = []
    for step in (-2, -1, 1, 2):
        nxt = clamp_northline_price(price + step)
        if nxt == price:
            continue
        # Move toward the public player basket, stay inside 86–120.
        utility = -abs(nxt - player_index) + (0.2 if step < 0 and player_index < price else 0)
        menu.append(
            (
                Action(actor=actor, kind="set_price_index", args={"price_index": nxt, "step": step}),
                utility,
            )
        )
    if blocks > 3:
        menu.append(
            (
                Action(actor=actor, kind="set_blocks", args={"blocks_away": clamp_blocks(blocks - 1)}),
                0.15,
            )
        )
    if reputation < 70:
        menu.append(
            (
                Action(actor=actor, kind="invest_reputation", args={"reputation": min(100, reputation + 1)}),
                0.1,
            )
        )
    menu.append((Action(actor=actor, kind="do_nothing", args={}), 0.0))
    # Touch the stream even when argmax does not need it, so the week is seeded.
    ai_rng(seed, "ai.north", week, "gate").random()
    chosen = argmax(menu)
    chosen.reason = northline_reason(chosen.kind)
    if chosen.kind == "set_price_index" and not (NORTHLINE_PRICE_MIN <= int(chosen.args["price_index"]) <= NORTHLINE_PRICE_MAX):
        chosen = Action(actor=actor, kind="do_nothing", args={}, reason=northline_reason("do_nothing"))
    return chosen


def allocate_bps(weights: dict[str, int]) -> dict[str, int]:
    return _allocate(weights)
