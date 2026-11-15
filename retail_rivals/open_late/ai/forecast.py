"""13-week projection.

With a city market and the shopper segments, sales and share come from the
same logit multipliers as the Sunday card. ``weekly_net`` still turns those
sales into cash. Without a market, the older single-elasticity surrogate
remains so a caller that only has a visit multiplier still gets a number.
Money is rounded only at the return.
"""

from __future__ import annotations

from open_late.ai.constants import BASE_WEEKLY_SALES, BUILD_WEEKLY_RATE, WEEKLY_RENT
from open_late.ai.costs import labor_multiplier, rent_multiplier, tax_drag_bps, traffic_mult
from open_late.ai.market import (
    apply_chain_action,
    apply_player_reply,
    card_units,
    chain_sales,
    chain_share,
)
from open_late.ai.models import ChainPnL, Projection, RivalChain, RivalStore


def _elasticity_units(price_index: int) -> float:
    ratio = max(1, price_index) / 100.0
    return ratio ** (-2.62)


def weekly_sales(price_index: int, visit_mult: int, promo_depth: int, shock_bps: int) -> int:
    promo = 1.0 + (max(0, promo_depth) / 100.0) * 0.55
    shock = 1.0 + shock_bps / 10_000.0
    raw = BASE_WEEKLY_SALES * _elasticity_units(price_index) * (visit_mult / 1000.0) * promo * shock
    return max(0, int(round(raw)))


def priced_margin_bps(gross_margin_bps: int, price_index: int, shelf_index: int) -> int:
    """Gross margin at a ticket. Cost of goods is locked at the shelf price.

    The personality margin is the rate at that chain's own shelf. A lower
    ticket comes out of margin, so a race to the floor stops paying.
    """
    if shelf_index <= 0 or price_index <= 0 or price_index >= shelf_index:
        return gross_margin_bps
    cogs_ratio = (1.0 - gross_margin_bps / 10_000.0) * (shelf_index / price_index)
    return int(round((1.0 - cogs_ratio) * 10_000))


def _drop_unearned_share(share_change_bps: int, net: int, hold_net: int) -> int:
    """Share does not pay for a move that earns less than standing still."""
    if share_change_bps > 0 and net < hold_net:
        return 0
    return share_change_bps


def weekly_net(
    sales: int,
    gross_margin_bps: int,
    opex_bps: int,
    *,
    promo_depth: int = 0,
    war_intensity: int = 0,
    cost_cut_pct: int = 0,
    debt: int = 0,
    rent: int | None = None,
    labor_mult: float = 1.0,
    rent_mult: float = 1.0,
    price_index: int | None = None,
    shelf_index: int | None = None,
) -> tuple[int, int, int]:
    """Return (net, cogs, opex_dollars), all integer dollars.

    Operating expense already includes occupancy. Factor 88 scales that slice.
    A caller that passes ``rent`` of 0 is not charged a second rent line.
    """
    gm_bps = priced_margin_bps(gross_margin_bps, int(price_index or 0), int(shelf_index or 0))
    gm = gm_bps / 10_000.0 - (promo_depth / 100.0) * 0.45 - war_intensity * 0.0015
    gm = max(-1.0, min(0.85, gm))
    ratio = (opex_bps / 10_000.0) * (1.0 - cost_cut_pct / 100.0)
    opex_rate = ratio * (0.65 * labor_mult + 0.35 * rent_mult)
    cogs = int(round(sales * (1.0 - gm)))
    opex = int(round(sales * opex_rate))
    interest = int(round(debt * BUILD_WEEKLY_RATE))
    door_rent = WEEKLY_RENT if rent is None else rent
    net = sales - cogs - opex - door_rent - interest
    return net, cogs, opex + door_rent + interest


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
        cash -= opening_cost - int(args.get("draw", 0))
        store_factor = 1
    elif kind == "reopen_store":
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
    market: list[dict] | None = None,
    segments: dict | None = None,
    income_by_city: dict[str, int] | None = None,
    player_type: str | None = None,
    baseline_market: list[dict] | None = None,
    factors: dict[str, int] | None = None,
    shelf_index: int | None = None,
) -> Projection:
    args = args or {}
    if market is not None and segments is not None:
        present = any(row.get("chain_id") == chain.chain_id for row in market)
        if present or kind == "open_store":
            return _project_logit(
                chain,
                gross_margin_bps=gross_margin_bps,
                opex_bps=opex_bps,
                kind=kind,
                args=args,
                opening_cost=opening_cost,
                shock_bps=shock_bps,
                horizon=horizon,
                debt_delta=debt_delta,
                market=market,
                segments=segments,
                income_by_city=income_by_city,
                player_type=player_type,
                baseline_market=baseline_market,
                factors=factors,
                shelf_index=shelf_index,
            )
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
    if kind == "open_store":
        debt += int(args.get("draw", 0))
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
        price_index=price,
        shelf_index=shelf_index,
    )
    contribution = net * horizon
    cash_end = cash + contribution
    old_price = chain.price_index
    share_change_bps = int(round((old_price - price) * 12))
    open_now = sum(1 for store in chain.stores if store.status == "open")
    hold_price = max(60, min(160, chain.price_index))
    hold_sales = weekly_sales(hold_price, visit_mult, 0, shock_bps) * open_now
    hold_net, _hold_cogs, _hold_opex = weekly_net(
        hold_sales,
        gross_margin_bps,
        opex_bps,
        cost_cut_pct=chain.cost_cut_pct,
        debt=max(0, chain.debt),
        price_index=hold_price,
        shelf_index=shelf_index,
    )
    share_change_bps = _drop_unearned_share(share_change_bps, net, hold_net)
    low_sales = weekly_sales(price, visit_mult, promo, shock_bps - 1000) * max(count, 1 if count else 0)
    high_sales = weekly_sales(price, visit_mult, promo, shock_bps + 1000) * max(count, 1 if count else 0)
    if count == 0:
        low_net = high_net = -WEEKLY_RENT * 0
        p10 = 0
        p90 = 0
    else:
        low_net, _, _ = weekly_net(
            low_sales,
            gross_margin_bps,
            opex_bps,
            promo_depth=promo,
            war_intensity=war,
            cost_cut_pct=cut,
            debt=debt,
            price_index=price,
            shelf_index=shelf_index,
        )
        high_net, _, _ = weekly_net(
            high_sales,
            gross_margin_bps,
            opex_bps,
            promo_depth=promo,
            war_intensity=war,
            cost_cut_pct=cut,
            debt=debt,
            price_index=price,
            shelf_index=shelf_index,
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


def _bundle(
    sales_map: dict[str, int],
    *,
    gross_margin_bps: int,
    opex_bps: int,
    promo: int,
    war: int,
    cut: int,
    debt: int,
    rent_by_store: dict[str, int] | None = None,
    labor_by_store: dict[str, float] | None = None,
    opex_extra_by_store: dict[str, int] | None = None,
    rent_mult_by_store: dict[str, float] | None = None,
    price_by_store: dict[str, int] | None = None,
    shelf_index: int | None = None,
) -> tuple[int, int]:
    """Return (sales, net) across the chain's doors. Occupancy sits inside opex."""
    if not sales_map:
        interest = int(round(max(0, debt) * BUILD_WEEKLY_RATE))
        return 0, -interest
    debt_share = max(0, debt) // len(sales_map)
    sales = 0
    net = 0
    rents = rent_by_store or {}
    labors = labor_by_store or {}
    extras = opex_extra_by_store or {}
    rent_mults = rent_mult_by_store or {}
    prices = price_by_store or {}
    for store_id, store_sales in sales_map.items():
        store_net, _cogs, _opex = weekly_net(
            store_sales,
            gross_margin_bps,
            opex_bps + int(extras.get(store_id, 0)),
            promo_depth=promo,
            war_intensity=war,
            cost_cut_pct=cut,
            debt=debt_share,
            rent=rents.get(store_id, 0),
            labor_mult=float(labors.get(store_id, 1.0)),
            rent_mult=float(rent_mults.get(store_id, 1.0)),
            price_index=int(prices.get(store_id, 100)),
            shelf_index=shelf_index,
        )
        sales += store_sales
        net += store_net
    return sales, net


def _door_factors(
    market: list[dict],
    factors: dict[str, int] | None,
) -> tuple[dict[str, int], dict[str, float], dict[str, int], dict[str, float], dict[str, float], dict[str, int]]:
    rents: dict[str, int] = {}
    labors: dict[str, float] = {}
    taxes: dict[str, int] = {}
    traffic: dict[str, float] = {}
    rent_mults: dict[str, float] = {}
    prices: dict[str, int] = {}
    for row in market:
        store_id = str(row.get("id", ""))
        city = str(row.get("city") or "")
        prices[store_id] = int(row.get("price_index", 100))
        if city not in {"evansville", "seattle", "houston", "las_vegas", "naperville"}:
            continue
        # Occupancy is inside opex. Dollar rent stays 0 so it is not charged again.
        rents[store_id] = 0
        rent_mults[store_id] = rent_multiplier(factors, city) if factors is not None else 1.0
        labors[store_id] = labor_multiplier(factors, city) if factors is not None else 1.0
        taxes[store_id] = tax_drag_bps(factors, city) if factors is not None else 0
        traffic[store_id] = traffic_mult(factors, city) if factors is not None else 1.0
    return rents, labors, taxes, traffic, rent_mults, prices


def _apply_traffic(sales: dict[str, int], traffic: dict[str, float]) -> dict[str, int]:
    if not traffic:
        return sales
    return {
        store_id: int(round(units * traffic.get(store_id, 1.0)))
        for store_id, units in sales.items()
    }


def _project_logit(
    chain: RivalChain,
    *,
    gross_margin_bps: int,
    opex_bps: int,
    kind: str,
    args: dict,
    opening_cost: int,
    shock_bps: int,
    horizon: int,
    debt_delta: int,
    market: list[dict],
    segments: dict,
    income_by_city: dict[str, int] | None,
    player_type: str | None,
    baseline_market: list[dict] | None,
    factors: dict[str, int] | None = None,
    shelf_index: int | None = None,
) -> Projection:
    _price, promo, war, cut, cash, _count = _effects(chain, kind, args, opening_cost)
    city = str(args.get("city", ""))
    acted = apply_chain_action(market, chain, kind, args, horizon=horizon)
    if baseline_market is None:
        base_rows = [dict(row) for row in market]
    else:
        base_rows = [dict(row) for row in baseline_market]
    if player_type:
        acted = apply_player_reply(acted, player_type, city)
        base_rows = apply_player_reply(base_rows, player_type, city)
    # Shock is a flat multiplier on units, so one logit covers the band.
    base_map = chain_sales(acted, chain.chain_id, segments, income_by_city, 0)
    rents, labors, taxes, traffic, rent_mults, prices = _door_factors(acted, factors)
    base_map = _apply_traffic(base_map, traffic)

    def _shocked(bps: int) -> dict[str, int]:
        scale = 1.0 + bps / 10_000.0
        return {store_id: int(round(units * scale)) for store_id, units in base_map.items()}

    sales_map = _shocked(shock_bps)
    low_map = _shocked(shock_bps - 1000)
    high_map = _shocked(shock_bps + 1000)
    new_share = chain_share(acted, chain.chain_id, segments, income_by_city)
    old_share = chain_share(base_rows, chain.chain_id, segments, income_by_city)
    debt = max(0, chain.debt + debt_delta)
    if kind == "raise_capital":
        debt += int(args.get("amount", 0))
    if kind == "open_store":
        debt += int(args.get("draw", 0))
    if kind == "pay_down_debt":
        debt = max(0, debt - int(args.get("amount", 0)))
    bundle = dict(
        gross_margin_bps=gross_margin_bps,
        opex_bps=opex_bps,
        promo=promo,
        war=war,
        cut=cut,
        debt=debt,
        rent_by_store=rents,
        labor_by_store=labors,
        opex_extra_by_store=taxes,
        rent_mult_by_store=rent_mults,
        price_by_store=prices,
        shelf_index=shelf_index,
    )
    sales, net = _bundle(sales_map, **bundle)
    _low_sales, low_net = _bundle(low_map, **bundle)
    _high_sales, high_net = _bundle(high_map, **bundle)
    contribution = net * horizon
    p10 = min(low_net * horizon, contribution)
    p90 = max(high_net * horizon, contribution)
    cash_end = cash + contribution
    p_neg = 1.0 if cash_end < 0 or cash + p10 < 0 else 0.0
    share_change_bps = int(round((new_share - old_share) * 10_000))
    if kind == "open_store":
        before = chain_sales(market, chain.chain_id, segments, income_by_city, 0)
        for store_id, units in sales_map.items():
            if store_id in before:
                continue
            door_net, _cogs, _opex = weekly_net(
                units,
                gross_margin_bps,
                opex_bps,
                promo_depth=promo,
                war_intensity=war,
                cost_cut_pct=cut,
                debt=0,
                rent=0,
                labor_mult=float(labors.get(store_id, 1.0)),
                rent_mult=float(rent_mults.get(store_id, 1.0)),
                price_index=int(prices.get(store_id, _price)),
                shelf_index=shelf_index,
            )
            coupon = int(round(int(args.get("draw", 0)) * BUILD_WEEKLY_RATE))
            if door_net <= coupon:
                share_change_bps = 0
                break
    if share_change_bps > 0:
        hold_rents, hold_labors, hold_taxes, hold_traffic, hold_rent_mults, hold_prices = _door_factors(
            base_rows, factors
        )
        hold_map = _apply_traffic(
            chain_sales(base_rows, chain.chain_id, segments, income_by_city, 0),
            hold_traffic,
        )
        hold_map = {store_id: int(round(units * (1.0 + shock_bps / 10_000.0))) for store_id, units in hold_map.items()}
        _hold_sales, hold_net = _bundle(
            hold_map,
            gross_margin_bps=gross_margin_bps,
            opex_bps=opex_bps,
            promo=0,
            war=0,
            cut=chain.cost_cut_pct,
            debt=max(0, chain.debt),
            rent_by_store=hold_rents,
            labor_by_store=hold_labors,
            opex_extra_by_store=hold_taxes,
            rent_mult_by_store=hold_rent_mults,
            price_by_store=hold_prices,
            shelf_index=shelf_index,
        )
        share_change_bps = _drop_unearned_share(share_change_bps, net, hold_net)
    return Projection(
        sales=sales,
        contribution=contribution,
        weekly_net=net,
        share_change_bps=share_change_bps,
        cash_end=cash_end,
        p_cash_negative=p_neg,
        p10_contribution=p10,
        p90_contribution=p90,
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
    factors: dict[str, int] | None = None,
    shelf_index: int | None = None,
) -> ChainPnL:
    price = max(1, store.price_index - (war_intensity // 2 if war_intensity else 0))
    sales = int(round(card_units(visit_mult, shock_bps) * price / 100.0))
    labor = 1.0
    extra = 0
    rent_mult = 1.0
    dollar_rent: int | None = None
    if factors is not None:
        labor = labor_multiplier(factors, store.city)
        extra = tax_drag_bps(factors, store.city)
        rent_mult = rent_multiplier(factors, store.city)
        dollar_rent = 0
    net, cogs, opex = weekly_net(
        sales,
        gross_margin_bps,
        opex_bps + extra,
        promo_depth=store.promo_depth,
        war_intensity=war_intensity,
        cost_cut_pct=cost_cut_pct,
        debt=debt_share,
        rent=dollar_rent,
        labor_mult=labor,
        rent_mult=rent_mult,
        price_index=price,
        shelf_index=shelf_index,
    )
    return ChainPnL(week=0, sales=sales, cogs=cogs, opex=opex, net=net)
