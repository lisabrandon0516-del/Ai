"""Rival chain CEOs.

One action per chain per week. Weekly moves are the belief-weighted value of
one step on the shopper logit. Big calls replace that score with a fixed
number of replies: our move, the player's answer drawn from the belief, then
our best follow-up. Temperature 0 is argmax with the spec tie-break.
"""

from __future__ import annotations

import hashlib

from open_late.ai.constants import (
    BIG_CALLS,
    DEPARTMENTS,
    PLAYER_TYPES,
    PRICE_INDEX_MAX,
    PRICE_INDEX_MIN,
    SEARCH_ITERS,
    SEARCH_SHORTLIST,
    SEGMENTS,
)
from open_late.ai.forecast import _effects, project_action
from open_late.ai.legal import ceo_menu, clamp_price
from open_late.ai.market import apply_chain_action, apply_player_reply, opened_store_id
from open_late.ai.memory import belief_means, recent_kinds, sample_player_type
from open_late.ai.models import Action, ActorMemory, ActorRef, Personality, RivalChain, RivalStore
from open_late.ai.reasons import ceo_reason
from open_late.ai.rng import ai_rng
from open_late.ai.select import argmax, softmax_pick, tie_key

# Used only when a caller has no city market. The logit path does not.
_REPLY_SCALE = {
    "price_fighter": 0.82,
    "premium": 1.06,
    "expander": 0.90,
    "passive": 1.0,
}


def _hostility(action: Action) -> float:
    if action.kind == "start_price_war":
        return 1.0
    if action.kind == "set_chain_price_index" and int(action.args.get("delta", 0)) < 0:
        return 0.7
    if action.kind == "defend":
        return 0.6
    if action.kind == "promo":
        return 0.3
    return 0.0


def _mandate_fit(
    action: Action,
    growth: int,
    archetype: str,
    *,
    chain_price: int = 100,
    shelf: int = 100,
) -> float:
    tilt = growth / 100.0
    if action.kind == "open_store":
        return tilt
    if action.kind == "pay_down_debt":
        return 1.0 - tilt
    if action.kind == "raise_capital":
        return tilt * 0.6
    if action.kind == "cut_costs":
        return 1.0 - tilt
    if action.kind == "set_chain_price_index":
        delta = int(action.args.get("delta", 0))
        if delta < 0:
            fit = 0.8 if archetype == "price_leader" else 0.3
        elif delta > 0:
            fit = 0.8 if archetype == "premium" else 0.2
        else:
            fit = 0.25
        before = abs(chain_price - shelf)
        after = abs(chain_price + delta - shelf)
        if after < before:
            fit += 0.8
        elif after > before:
            fit -= 0.6
        return fit
    return 0.25


def _preferred_dept(segments: dict | None, income: int) -> str:
    """The department this city's shoppers already prefer. Grocery if we cannot tell."""
    if not segments:
        return "grocery"
    from open_late.ai.shoppers import segment_mix

    mix = segment_mix(income)
    best = "grocery"
    best_score = -1.0
    for dept in DEPARTMENTS:
        score = 0.0
        for name in SEGMENTS:
            score += float(mix.get(name, 0.0)) * float(segments[name].get("depts", {}).get(dept, 1.0))
        if score > best_score or (score == best_score and dept < best):
            best = dept
            best_score = score
    return best


def _city_posture(
    archetype: str,
    city: str,
    chain: RivalChain,
    income_by_city: dict[str, int] | None,
    occupied: int = 0,
) -> float:
    """Break a tie between cities. Income fit, who is already there, and a stable nudge."""
    income = int((income_by_city or {}).get(city, 100))
    here = sum(1 for store in chain.stores if store.city == city and store.status in {"open", "building"})
    if archetype == "premium":
        fit = (income - 100) / 20.0
    elif archetype == "price_leader":
        fit = (100 - income) / 20.0
    else:
        fit = 0.8 if here == 0 else -0.4
    fit -= 0.6 * here
    fit -= 1.2 * occupied
    digest = hashlib.blake2s(f"{chain.chain_id}|{city}".encode(), digest_size=2).digest()
    nudge = (int.from_bytes(digest, "little") / 65535.0 - 0.5) * 0.6
    return fit + nudge


def _opening_bill(action: Action, opening_cost: int) -> int:
    if action.kind == "open_store":
        return int(action.args.get("cost", opening_cost))
    return opening_cost


def _cash_risk(action: Action, chain: RivalChain, p_negative: float) -> float:
    """Once the drawer is empty, drawing the credit line is the move that keeps the chain alive."""
    undrawn = chain.debt < chain.credit_line
    if chain.cash < 0 and undrawn:
        if action.kind == "raise_capital":
            return 8.0
        return -2.0
    return -p_negative


def _regret(action: Action, memory: ActorMemory, week: int) -> float:
    recent = recent_kinds(memory, 4, week)
    delta = int(action.args.get("delta", 0)) if action.kind == "set_chain_price_index" else 0
    for row in recent:
        if action.kind == "end_price_war" and row.get("kind") == "start_price_war" and row.get("city") == action.args.get("city"):
            return -1.0
        if action.kind == "close_store" and row.get("kind") == "open_store" and row.get("city") == action.args.get("city"):
            return -1.0
        if action.kind == "set_chain_price_index" and row.get("kind") == "set_chain_price_index":
            previous = int(row.get("delta", 0))
            if previous and delta and (previous > 0) != (delta > 0):
                return -1.0
    return 0.0


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
        shadow.debt += int(args.get("amount", 0))
    elif kind == "open_store":
        shadow.debt += int(args.get("draw", 0))
    elif kind == "pay_down_debt":
        shadow.debt = max(0, shadow.debt - int(args.get("amount", 0)))
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
    elif kind == "cut_costs":
        shadow.cost_cut_pct = int(args.get("pct", cut))
    return shadow


def follow_up_actions(chain: RivalChain, first: Action) -> list[Action]:
    """Small second move. The search argmaxes this; it does not draw it."""
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


def _terms(
    action: Action,
    chain: RivalChain,
    personality: Personality,
    memory: ActorMemory,
    *,
    week: int,
    opening_cost: int,
    visit_mult: int,
    shock_bps: int,
    market: list[dict] | None = None,
    segments: dict | None = None,
    income_by_city: dict[str, int] | None = None,
    player_type: str | None = None,
    baseline_market: list[dict] | None = None,
    factors: dict[str, int] | None = None,
) -> dict[str, float]:
    scaled = visit_mult
    if market is None and player_type:
        scaled = int(round(visit_mult * _REPLY_SCALE.get(player_type, 1.0)))
    bill = _opening_bill(action, opening_cost)
    projected = project_action(
        chain,
        gross_margin_bps=personality.gross_margin_bps,
        opex_bps=personality.opex_bps,
        kind=action.kind,
        args=action.args,
        opening_cost=bill,
        visit_mult=scaled,
        shock_bps=shock_bps,
        market=market,
        segments=segments,
        income_by_city=income_by_city,
        player_type=player_type,
        baseline_market=baseline_market,
        factors=factors,
        shelf_index=personality.price_index,
    )
    last = ""
    if memory.moves:
        last = str(memory.moves[-1].get("kind", ""))
    contribution = projected.contribution
    if action.kind == "remodel":
        # The forecast does not grow sales for a remodel, so the check is a real cost.
        contribution -= int(action.args.get("cost", 0))
    return {
        "contribution_13w": contribution / 1_000_000.0,
        # /500 keeps one share-point near the weight scale the personalities
        # shipped with. Raw basis points would drown every other term.
        "share_change": projected.share_change_bps / 500.0,
        "cash_risk": _cash_risk(action, chain, projected.p_cash_negative),
        "mandate_fit": _mandate_fit(
            action,
            chain.mandate.growth_vs_profit,
            personality.archetype,
            chain_price=chain.price_index,
            shelf=personality.price_index,
        )
        + (
            _city_posture(
                personality.archetype,
                str(action.args.get("city", "")),
                chain,
                income_by_city,
                occupied=sum(
                    1
                    for row in (market or [])
                    if row.get("city") == action.args.get("city")
                    and row.get("chain_id") not in {chain.chain_id, "online"}
                    and row.get("id") != "online"
                ),
            )
            if action.kind == "open_store"
            else 0.0
        ),
        "grudge": (memory.grudge / 100.0) * _hostility(action),
        "variety": -1.0 if last == action.kind else 0.0,
        "regret": _regret(action, memory, week),
    }


def _utility(terms: dict[str, float], weights: dict[str, float]) -> float:
    return sum(float(weights.get(name, 0.0)) * value for name, value in terms.items())


def _blended_terms(
    action: Action,
    chain: RivalChain,
    personality: Personality,
    memory: ActorMemory,
    *,
    week: int,
    opening_cost: int,
    visit_mult: int,
    market: list[dict] | None,
    segments: dict | None,
    income_by_city: dict[str, int] | None,
    factors: dict[str, int] | None = None,
) -> dict[str, float]:
    means = belief_means(memory.belief_or_prior())
    totals: dict[str, float] = {}
    for name in PLAYER_TYPES:
        prob = float(means.get(name, 0.0))
        if prob <= 0:
            continue
        terms = _terms(
            action,
            chain,
            personality,
            memory,
            week=week,
            opening_cost=opening_cost,
            visit_mult=visit_mult,
            shock_bps=0,
            market=market,
            segments=segments,
            income_by_city=income_by_city,
            player_type=name,
            factors=factors,
        )
        for key, value in terms.items():
            totals[key] = totals.get(key, 0.0) + prob * value
    return totals


def _continuation_utility(
    action: Action,
    chain: RivalChain,
    personality: Personality,
    memory: ActorMemory,
    *,
    week: int,
    opening_cost: int,
    visit_mult: int,
    player_type: str,
    market: list[dict] | None,
    segments: dict | None,
    income_by_city: dict[str, int] | None,
    factors: dict[str, int] | None = None,
) -> float:
    """Our move, their reply, then the best follow-up on that position."""
    chain1 = advance_chain(chain, action, _opening_bill(action, opening_cost))
    city = str(action.args.get("city", ""))
    baseline = None
    positioned = market
    if market is not None:
        baseline = apply_player_reply(market, player_type, city)
        positioned = apply_player_reply(apply_chain_action(market, chain, action.kind, action.args), player_type, city)
    best: float | None = None
    for follow in follow_up_actions(chain1, action):
        terms = _terms(
            follow,
            chain1,
            personality,
            memory,
            week=week,
            opening_cost=opening_cost,
            visit_mult=visit_mult,
            shock_bps=0,
            market=positioned,
            segments=segments,
            income_by_city=income_by_city,
            player_type=None if market is not None else player_type,
            baseline_market=baseline,
            factors=factors,
        )
        utility = _utility(terms, personality.weights)
        if best is None or utility > best:
            best = utility
    return 0.0 if best is None else best


def _expectimax(
    action: Action,
    chain: RivalChain,
    personality: Personality,
    memory: ActorMemory,
    *,
    seed: int,
    week: int,
    opening_cost: int,
    visit_mult: int,
    iters: int,
    market: list[dict] | None = None,
    segments: dict | None = None,
    income_by_city: dict[str, int] | None = None,
    factors: dict[str, int] | None = None,
) -> tuple[float, dict[str, float]]:
    means = belief_means(memory.belief_or_prior())
    total = 0.0
    city = str(action.args.get("city", ""))
    for index in range(iters):
        rng = ai_rng(seed, "ai.search", week, chain.chain_id, action.kind, city, index)
        player_type = sample_player_type(rng, means)
        total += _continuation_utility(
            action,
            chain,
            personality,
            memory,
            week=week,
            opening_cost=opening_cost,
            visit_mult=visit_mult,
            player_type=player_type,
            market=market,
            segments=segments,
            income_by_city=income_by_city,
            factors=factors,
        )
    base = _blended_terms(
        action,
        chain,
        personality,
        memory,
        week=week,
        opening_cost=opening_cost,
        visit_mult=visit_mult,
        market=market,
        segments=segments,
        income_by_city=income_by_city,
        factors=factors,
    )
    if iters <= 0:
        return _utility(base, personality.weights), base
    return total / iters, base


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
) -> Action:
    menu = ceo_menu(
        chain,
        week,
        opening_cost,
        wars,
        remodel_cost=remodel_cost,
        raise_amount=raise_amount,
        opening_costs=opening_costs,
    )
    if not menu:
        actor_id = f"ceo:{chain.chain_id}"
        action = Action(actor=ActorRef(kind="ceo", id=actor_id), kind="do_nothing", args={})
        action.reason = ceo_reason(chain.chain_id, action.kind, action.args)
        return action

    kept: list[Action] = []
    for action in menu:
        if action.kind == "defend":
            city = str(action.args.get("city", ""))
            action.args["match_index"] = int(player_price.get(city, chain.price_index))
        if action.kind == "copy_best_seller":
            city = str(action.args.get("city", ""))
            income = int((income_by_city or {}).get(city, 100))
            dept = _preferred_dept(segments, income)
            action.args["dept"] = dept
            focused = [
                store
                for store in chain.stores
                if store.city == city and store.status == "open" and store.focus_dept == dept
            ]
            if focused:
                continue
        kept.append(action)
    # Don't build on top of a door that is already there. An empty city is the
    # only opening, so chains spread out instead of stacking in the first one
    # that looks profitable.
    def _occupied(action: Action) -> int:
        return sum(
            1
            for row in (market or [])
            if row.get("city") == action.args.get("city")
            and row.get("chain_id") not in {chain.chain_id, "online"}
            and row.get("id") != "online"
        )

    kept = [action for action in kept if action.kind != "open_store" or _occupied(action) == 0]
    menu = kept

    scored: list[tuple[Action, float, dict[str, float]]] = []
    for action in menu:
        terms = _blended_terms(
            action,
            chain,
            personality,
            memory,
            week=week,
            opening_cost=opening_cost,
            visit_mult=visit_mult,
            market=market,
            segments=segments,
            income_by_city=income_by_city,
            factors=factors,
        )
        scored.append((action, _utility(terms, personality.weights), terms))

    iters = SEARCH_ITERS.get(difficulty, SEARCH_ITERS["standard"])
    big = [row for row in scored if row[0].kind in BIG_CALLS]
    big.sort(key=lambda row: (-round(row[1], 6), tie_key(row[0])))
    for action, _myopic, _myopic_terms in big[:SEARCH_SHORTLIST]:
        mean_u, terms = _expectimax(
            action,
            chain,
            personality,
            memory,
            seed=seed,
            week=week,
            opening_cost=opening_cost,
            visit_mult=visit_mult,
            iters=iters,
            market=market,
            segments=segments,
            income_by_city=income_by_city,
            factors=factors,
        )
        for index, row in enumerate(scored):
            if row[0] is action:
                scored[index] = (action, mean_u, terms)
                break

    pairs = [(action, utility) for action, utility, _terms in scored]
    if personality.temperature > 0:
        rng = ai_rng(seed, "ai.ceo", week, chain.chain_id, "softmax")
        chosen = softmax_pick(pairs, rng, personality.temperature)
    else:
        chosen = argmax(pairs)
    terms = next(item[2] for item in scored if item[0] is chosen)
    chosen.utility_terms = {key: round(value, 6) for key, value in terms.items()}
    chosen.reason = ceo_reason(chain.chain_id, chosen.kind, chosen.args)
    return chosen
