"""Rival chain CEOs.

One action per chain per week. Weekly moves use a one-step score. Big calls
replace that score with a fixed-iteration expectimax on the cheap projection.
Temperature 0 is argmax with the spec tie-break.
"""

from __future__ import annotations

from open_late.ai.constants import BIG_CALLS, SEARCH_ITERS, SEARCH_SHORTLIST
from open_late.ai.forecast import project_action
from open_late.ai.legal import ceo_menu
from open_late.ai.memory import recent_kinds
from open_late.ai.models import Action, ActorMemory, Personality, RivalChain
from open_late.ai.reasons import ceo_reason
from open_late.ai.rng import ai_rng
from open_late.ai.select import argmax, softmax_pick, tie_key


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
) -> dict[str, float]:
    debt_delta = 0
    projected = project_action(
        chain,
        gross_margin_bps=personality.gross_margin_bps,
        opex_bps=personality.opex_bps,
        kind=action.kind,
        args=action.args,
        opening_cost=opening_cost,
        visit_mult=visit_mult,
        shock_bps=shock_bps,
        debt_delta=debt_delta,
    )
    last = ""
    if memory.moves:
        last = str(memory.moves[-1].get("kind", ""))
    return {
        "contribution_13w": projected.contribution / 1_000_000.0,
        "share_change": projected.share_change_bps / 100.0,
        "cash_risk": -projected.p_cash_negative,
        "mandate_fit": _mandate_fit(action, chain.mandate.growth_vs_profit, personality.archetype),
        "grudge": (memory.grudge / 100.0) * _hostility(action),
        "variety": -1.0 if last == action.kind else 0.0,
        "regret": _regret(action, memory, week),
    }


def _utility(terms: dict[str, float], weights: dict[str, float]) -> float:
    return sum(float(weights.get(name, 0.0)) * value for name, value in terms.items())


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
) -> tuple[float, dict[str, float]]:
    total = 0.0
    city = str(action.args.get("city", ""))
    for index in range(iters):
        rng = ai_rng(seed, "ai.search", week, chain.chain_id, action.kind, city, index)
        shock = rng.choice([-1000, 0, 1000])
        terms = _terms(
            action,
            chain,
            personality,
            memory,
            week=week,
            opening_cost=opening_cost,
            visit_mult=visit_mult,
            shock_bps=shock,
        )
        total += _utility(terms, personality.weights)
    if iters <= 0:
        terms = _terms(
            action, chain, personality, memory, week=week, opening_cost=opening_cost, visit_mult=visit_mult, shock_bps=0
        )
        return _utility(terms, personality.weights), terms
    # Report the zero-shock terms; the utility is the mean of the rollouts.
    base_terms = _terms(
        action, chain, personality, memory, week=week, opening_cost=opening_cost, visit_mult=visit_mult, shock_bps=0
    )
    return total / iters, base_terms


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
        from open_late.ai.models import ActorRef

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
        terms = _terms(
            action,
            chain,
            personality,
            memory,
            week=week,
            opening_cost=opening_cost,
            visit_mult=visit_mult,
            shock_bps=0,
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
