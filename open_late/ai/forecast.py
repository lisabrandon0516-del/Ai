"""Closed-form 13-week projection.

This is the cheap surrogate the minds look ahead on. It is not a fork of the
game. The stand-in week uses the same weekly_net so a paired check stays
inside the 15% band by construction. Money is rounded only at the return.
"""

from __future__ import annotations

from open_late.ai.constants import BASE_WEEKLY_SALES, WEEKLY_RENT
from open_late.ai.models import ChainPnL, Projection, RivalChain, RivalStore


def _elasticity_units(price_index: int) -> float:
    ratio = max(1, price_index) / 100.0
    return ratio ** (-2.62)


def weekly_sales(price_index: int, visit_mult: int, promo_depth: int, shock_bps: int) -> int:
    promo = 1.0 + (max(0, promo_depth) / 100.0) * 0.55
    shock = 1.0 + shock_bps / 10_000.0
    raw = BASE_WEEKLY_SALES * _elasticity_units(price_index) * (visit_mult / 1000.0) * promo * shock
    return max(0, int(round(raw)))


def weekly_net(
    sales: int,
    gross_margin_bps: int,
    opex_bps: int,
    *,
    promo_depth: int = 0,
    war_intensity: int = 0,
    cost_cut_pct: int = 0,
    debt: int = 0,
) -> tuple[int, int, int]:
    """Return (net, cogs, opex_dollars), all integer dollars."""
    gm = gross_margin_bps / 10_000.0 - (promo_depth / 100.0) * 0.45 - war_intensity * 0.0015
    opex_rate = (opex_bps / 10_000.0) * (1.0 - cost_cut_pct / 100.0)
    gm = max(0.0, gm)
    cogs = int(round(sales * (1.0 - gm)))
    opex = int(round(sales * opex_rate))
    interest = int(round(debt * 0.001))
    net = sales - cogs - opex - WEEKLY_RENT - interest
    return net, cogs, opex + WEEKLY_RENT + interest


def _effects(
    chain: RivalChain,
    kind: str,
    args: dict,
    opening_cost: int,
) -> tuple[int, int, int, int, int, int]:
    """Return price, promo, war, cost_cut, cash0, extra_stores_selling_weeks_factor.

    The last value is how many of the chain's open-store equivalents sell.
    """
    price = chain.price_index
    promo = 0
    war = 0
    cut = chain.cost_cut_pct
    cash = chain.cash
    store_factor = 0
    open_stores = [store for store in chain.stores if store.status == "open"]
    for store in open_stores:
        promo = max(promo, store.promo_depth)
    if kind == "set_chain_price_index":
        price = price + int(args.get("delta", 0))
    elif kind == "defend":
        target = int(args.get("match_index", price))
        price = target
    elif kind == "start_price_war":
        war = int(args.get("intensity", 8))
        price = price - war // 2
    elif kind == "promo":
        promo = int(args.get("depth", 20))
    elif kind == "cut_costs":
        cut = int(args.get("pct", 1))
    elif kind == "open_store":
        cash -= opening_cost
        store_factor = 1
    elif kind == "close_store":
        store_factor = -1
    elif kind == "remodel":
        cash -= int(args.get("cost", 500_000))
    elif kind == "raise_capital":
        amount = int(args.get("amount", 0))
        cash += amount
    elif kind == "pay_down_debt":
        cash -= int(args.get("amount", 0))
    elif kind == "markdown":
        price -= 2
    base_count = max(0, len(open_stores) + store_factor)
    return price, promo, war, cut, cash, base_count


def project_action(
    chain: RivalChain,
    *,
    gross_margin_bps: int,
    opex_bps: int,
    kind: str = "do_nothing",
    args: dict | None = None,
    opening_cost: int = 0,
    visit_mult: int = 1000,
    shock_bps: int = 0,
    horizon: int = 13,
    debt_delta: int = 0,
) -> Projection:
    args = args or {}
    price, promo, war, cut, cash, count = _effects(chain, kind, args, opening_cost)
    price = max(60, min(160, price))
    count = max(0, count)
    # A new store sells for only part of the horizon (permit delay).
    if kind == "open_store":
        delay = int(args.get("delay_weeks", 4))
        new_weeks = max(0, horizon - delay)
        old_count = max(0, count - 1)
        sales_one = weekly_sales(price, visit_mult, promo, shock_bps)
        # Blend: existing stores for the full horizon, the new door after the delay.
        avg_count = old_count + (new_weeks / max(1, horizon))
        sales = int(round(sales_one * max(avg_count, 0.0)))
    else:
        sales_one = weekly_sales(price, visit_mult, promo, shock_bps)
        sales = sales_one * count
    debt = max(0, chain.debt + debt_delta)
    if kind == "raise_capital":
        debt += int(args.get("amount", 0))
    if kind == "pay_down_debt":
        debt = max(0, debt - int(args.get("amount", 0)))
    net, cogs, opex = weekly_net(
        sales,
        gross_margin_bps,
        opex_bps,
        promo_depth=promo,
        war_intensity=war,
        cost_cut_pct=cut,
        debt=debt,
    )
    contribution = net * horizon
    cash_end = cash + contribution
    old_price = chain.price_index
    share_change_bps = int(round((old_price - price) * 12))
    low_sales = weekly_sales(price, visit_mult, promo, shock_bps - 1000) * max(count, 1 if count else 0)
    high_sales = weekly_sales(price, visit_mult, promo, shock_bps + 1000) * max(count, 1 if count else 0)
    if count == 0:
        low_net = high_net = -WEEKLY_RENT * 0
        p10 = 0
        p90 = 0
    else:
        low_net, _, _ = weekly_net(
            low_sales, gross_margin_bps, opex_bps, promo_depth=promo, war_intensity=war, cost_cut_pct=cut, debt=debt
        )
        high_net, _, _ = weekly_net(
            high_sales, gross_margin_bps, opex_bps, promo_depth=promo, war_intensity=war, cost_cut_pct=cut, debt=debt
        )
        p10 = low_net * horizon
        p90 = high_net * horizon
    p_neg = 1.0 if cash_end < 0 or (count > 0 and cash + (p10) < 0) else 0.0
    if p10 > contribution:
        p10, contribution = contribution, contribution
        p10 = min(p10, contribution)
    p10_c = min(p10, contribution)
    p90_c = max(p90, contribution)
    return Projection(
        sales=sales,
        contribution=contribution,
        weekly_net=net,
        share_change_bps=share_change_bps,
        cash_end=cash_end,
        p_cash_negative=p_neg,
        p10_contribution=p10_c,
        p90_contribution=p90_c,
    )


def store_pnl(
    store: RivalStore,
    *,
    gross_margin_bps: int,
    opex_bps: int,
    visit_mult: int,
    war_intensity: int,
    cost_cut_pct: int,
    debt_share: int,
    shock_bps: int = 0,
) -> ChainPnL:
    price = store.price_index - (war_intensity // 2 if war_intensity else 0)
    sales = weekly_sales(price, visit_mult, store.promo_depth, shock_bps)
    net, cogs, opex = weekly_net(
        sales,
        gross_margin_bps,
        opex_bps,
        promo_depth=store.promo_depth,
        war_intensity=war_intensity,
        cost_cut_pct=cost_cut_pct,
        debt=debt_share,
    )
    return ChainPnL(week=0, sales=sales, cogs=cogs, opex=opex, net=net)
