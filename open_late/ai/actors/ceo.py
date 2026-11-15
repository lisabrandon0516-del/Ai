"""Rival chain CEOs.

One action per chain per week. Weekly moves are the belief-weighted value of
one step on the shopper logit. Big calls replace that score with a fixed
number of replies: our move, the player's answer drawn from the belief, then
our best follow-up. Temperature 0 is argmax with the spec tie-break.
"""

from __future__ import annotations

from open_late.ai.constants import BIG_CALLS, PLAYER_TYPES, PRICE_INDEX_MAX, PRICE_INDEX_MIN, SEARCH_ITERS, SEARCH_SHORTLIST
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


def _mandate_fit(action: Action, growth: int, archetype: str) -> float:
    tilt = growth / 100.0
    if action.kind == "open_store":
        return tilt
    if action.kind == "pay_down_debt":
        return 1.0 - tilt
    if action.kind == "raise_capital":
        return tilt * 0.6
    if action.kind == "cut_costs":
        return 1.0 - tilt
    if action.kind == "set_chain_price_index" and int(action.args.get("delta", 0)) < 0:
        return 0.8 if archetype == "price_leader" else 0.3
    if action.kind == "set_chain_price_index" and int(action.args.get("delta", 0)) > 0:
        return 0.8 if archetype == "premium" else 0.2
    return 0.25


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
) -> dict[str, float]:
    scaled = visit_mult
    if market is None and player_type:
        scaled = int(round(visit_mult * _REPLY_SCALE.get(player_type, 1.0)))
    projected = project_action(
        chain,
        gross_margin_bps=personality.gross_margin_bps,
        opex_bps=personality.opex_bps,
        kind=action.kind,
        args=action.args,
        opening_cost=opening_cost,
        visit_mult=scaled,
        shock_bps=shock_bps,
        market=market,
        segments=segments,
        income_by_city=income_by_city,
        player_type=player_type,
        baseline_market=baseline_market,
    )
    last = ""
    if memory.moves:
        last = str(memory.moves[-1].get("kind", ""))
    return {
        "contribution_13w": projected.contribution / 1_000_000.0,
        # /500 keeps one share-point near the weight scale the personalities
        # shipped with. Raw basis points would drown every other term.
        "share_change": projected.share_change_bps / 500.0,
        "cash_risk": -projected.p_cash_negative,
        "mandate_fit": _mandate_fit(action, chain.mandate.growth_vs_profit, personality.archetype),
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
) -> float:
    """Our move, their reply, then the best follow-up on that position."""
    chain1 = advance_chain(chain, action, opening_cost)
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
) -> Action:
    menu = ceo_menu(
        chain,
        week,
        opening_cost,
        wars,
        remodel_cost=remodel_cost,
        raise_amount=raise_amount,
    )
    if not menu:
        actor_id = f"ceo:{chain.chain_id}"
        action = Action(actor=ActorRef(kind="ceo", id=actor_id), kind="do_nothing", args={})
        action.reason = ceo_reason(chain.chain_id, action.kind, action.args)
        return action

    for action in menu:
        if action.kind == "defend":
            city = str(action.args.get("city", ""))
            action.args["match_index"] = int(player_price.get(city, chain.price_index))
        if action.kind == "copy_best_seller":
            action.args["dept"] = "grocery"

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
