"""Baseline rival policies. Test-only. They never ship in the player build."""

from __future__ import annotations

from open_late.ai.legal import ceo_menu
from open_late.ai.models import Action, ActorRef, RivalChain
from open_late.ai.reasons import ceo_reason
from open_late.ai.rng import ai_rng
from open_late.ai.select import argmax


def static_action(chain: RivalChain) -> Action:
    action = Action(actor=ActorRef(kind="ceo", id=f"ceo:{chain.chain_id}"), kind="do_nothing", args={})
    action.reason = ceo_reason(chain.chain_id, "do_nothing", {})
    return action


def random_action(chain: RivalChain, *, seed: int, week: int, opening_cost: int, wars: dict[str, int]) -> Action:
    menu = ceo_menu(chain, week, opening_cost, wars)
    if not menu:
        return static_action(chain)
    rng = ai_rng(seed, "ai.tune", week, chain.chain_id, "random")
    index = rng.randrange(len(menu))
    # Walk in menu order so the draw is stable even if menu order is.
    chosen = menu[index]
    chosen.reason = ceo_reason(chain.chain_id, chosen.kind, chosen.args)
    return chosen


def greedy_action(
    chain: RivalChain,
    contributions: list[tuple[Action, int]],
) -> Action:
    """1-step argmax of next-week contribution. No memory and no look-ahead."""
    if not contributions:
        return static_action(chain)
    chosen = argmax([(action, float(value)) for action, value in contributions])
    chosen.reason = ceo_reason(chain.chain_id, chosen.kind, chosen.args)
    return chosen


def scripted_action(
    chain: RivalChain,
    *,
    week: int,
    player_index: int,
    opening_cost: int,
    wars: dict[str, int],
) -> Action:
    """War when the gap is at least 3 and the cooldown is clear; copy focus
    every 4 weeks; expand when cash allows. Otherwise hold.
    """
    menu = ceo_menu(chain, week, opening_cost, wars)
    by_kind: dict[str, list[Action]] = {}
    for action in menu:
        by_kind.setdefault(action.kind, []).append(action)
    gap = chain.price_index - player_index
    if gap >= 3 and by_kind.get("start_price_war"):
        chosen = by_kind["start_price_war"][0]
    elif week % 4 == 0 and by_kind.get("copy_best_seller"):
        chosen = by_kind["copy_best_seller"][0]
    elif chain.cash >= opening_cost + 2_000_000 and by_kind.get("open_store"):
        chosen = by_kind["open_store"][0]
    else:
        chosen = by_kind.get("do_nothing", [static_action(chain)])[0]
    chosen.reason = ceo_reason(chain.chain_id, chosen.kind, chosen.args)
    return chosen
