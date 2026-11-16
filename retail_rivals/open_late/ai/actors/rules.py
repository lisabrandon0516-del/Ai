"""Weekly rules for a rival chief executive.

Every week uses a short list of readable rules. The year-ahead forecast runs
only for a city that might be opened or a door that might be closed, once per
city per week.
"""

from __future__ import annotations

from open_late.ai.books import trailing_ebitda
from open_late.ai.constants import (
    BUILD_LTV,
    BUILD_TERM_WEEKS,
    BUILD_WEEKLY_RATE,
    CANNIBAL_MAX,
    CITIES,
    DEPARTMENTS,
    MIN_CASH_WEEKS,
    OPENING_COOLDOWN_WEEKS,
    SEGMENTS,
)
from open_late.ai.forecast import store_pnl, year_ahead_profit
from open_late.ai.legal import board_blocks, build_loan_terms, clamp_price, last_store_cannot_earn
from open_late.ai.market import chain_sales
from open_late.ai.models import Action, ActorMemory, ActorRef, Personality, RivalChain, RivalStore
from open_late.ai.reasons import reason
from open_late.ai.select import argmax
from open_late.ai.shoppers import choice_shares, segment_mix, visit_multipliers

# Named peaks from the economy calendar, not the long seasons around them.
_PEAK_WEEKS = frozenset({7, 26, 32, 33, 34, 35, 43, 44, 47, 48, 49, 50, 51})

# How much discounted year-ahead profit a door must clear, before the growth tilt.
# Year-ahead store profit, before the loan payment. The loan still has to cover itself.
# Expanders take a weaker door. A price leader waits for a stronger one.
# Year-ahead of the shopper volume, before the loan payment. A split door is
# worth less than an empty city, so the low bar still refuses a crowded one.
_OPEN_BAR = {"expander": 0, "premium": 1_200_000, "price_leader": 3_000_000}

_FORECASTS: dict[tuple, int] = {}


def clear_forecast_cache() -> None:
    _FORECASTS.clear()


def _actor(chain: RivalChain) -> ActorRef:
    return ActorRef(kind="ceo", id=f"ceo:{chain.chain_id}")


def _done(chain: RivalChain, kind: str, args: dict, text: str) -> Action:
    action = Action(actor=_actor(chain), kind=kind, args=args)
    action.reason = reason(text)
    return action


def _name(chain: RivalChain) -> str:
    from open_late.ai.constants import chain_name

    return chain_name(chain.chain_id)


def _peak(week: int) -> bool:
    return (week % 52) in _PEAK_WEEKS


def _step(personality: Personality) -> int:
    """A chain that cares more about share moves the ticket by a larger step."""
    share = float(personality.weights.get("share_change", 1.0))
    return 4 if share >= 2.0 else 2


def _open_bar(personality: Personality) -> int:
    base = _OPEN_BAR.get(personality.archetype, _OPEN_BAR["premium"])
    weight = float(personality.weights.get("contribution_13w", 1.0))
    # Zeroing the profit weight, as a tuning run does, makes the chain wait.
    return base + int(max(0.0, 1.0 - weight) * 1_500_000)


def _share_drop_points(personality: Personality) -> float:
    base = {"price_leader": 1.0, "expander": 2.0, "premium": 3.0}.get(personality.archetype, 2.0)
    share = float(personality.weights.get("share_change", 1.0))
    return max(0.5, base - max(0.0, share - 1.0))


def _preferred_dept(segments: dict | None, income: int) -> str:
    if not segments:
        return "grocery"
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


def _city_share_bps(market: list[dict], chain: RivalChain, city: str, segments: dict, income: int) -> int | None:
    local = [row for row in market if row.get("city") in {city, ""} or row.get("id") == "online"]
    ours = [row for row in local if row.get("chain_id") == chain.chain_id and row.get("city") == city]
    if not ours or segments is None:
        return None
    shares = choice_shares(local, segments, income_index=income)
    physical = [row for row in local if row.get("id") != "online"]
    total = sum(shares.get(str(row.get("id")), 0.0) for row in physical) or 1.0
    owned = sum(shares.get(str(row.get("id")), 0.0) for row in ours)
    return int(round(10_000 * owned / total))


def _note_share(memory: ActorMemory, city: str, bps: int) -> int | None:
    trail = memory.share_trail.setdefault(city, [])
    previous = trail[0] if len(trail) >= 4 else None
    trail.append(int(bps))
    if len(trail) > 4:
        del trail[:-4]
    return previous


def _open_stores(chain: RivalChain) -> list[RivalStore]:
    return [store for store in chain.stores if store.status == "open"]


def _weekly_opex(chain: RivalChain, personality: Personality, factors: dict | None) -> int:
    if chain.last_pnl.opex > 0:
        return chain.last_pnl.opex
    total = 0
    for store in _open_stores(chain):
        pnl = store_pnl(
            store,
            gross_margin_bps=personality.gross_margin_bps,
            opex_bps=personality.opex_bps,
            visit_mult=1000,
            war_intensity=0,
            cost_cut_pct=chain.cost_cut_pct,
            debt_share=0,
            factors=factors,
            shelf_index=personality.price_index,
        )
        total += pnl.opex
    return total


def _loan_payment(loan: int) -> int:
    if loan <= 0:
        return 0
    return int(round(loan * BUILD_WEEKLY_RATE)) + max(1, loan // BUILD_TERM_WEEKS)


def _remember_block(memory: ActorMemory, text: str) -> None:
    del text
    memory.counters["open_blocked"] = memory.counters.get("open_blocked", 0) + 1


def city_forecast(chain_id: str, week: int, city: str, price_index: int, weekly_net: int, *, delay: int = 4) -> int:
    """Year-ahead value for one city. A second ask in the same week is free."""
    key = (chain_id, int(week), city, int(price_index), int(delay))
    cached = _FORECASTS.get(key)
    if cached is not None:
        return cached
    value = year_ahead_profit(weekly_net, delay_weeks=delay)
    if len(_FORECASTS) > 4096:
        _FORECASTS.clear()
    _FORECASTS[key] = value
    return value


def _probe_row(chain: RivalChain, city: str) -> dict:
    return {
        "id": f"probe:{chain.chain_id}:{city}",
        "city": city,
        "owner": "rival",
        "chain_id": chain.chain_id,
        "price_index": chain.price_index,
        "distance_band": 2,
        "trust": 50,
        "promo": 0,
        "stockouts": 0,
        "focus": "grocery",
        "planogram": 50,
        "selection": 50,
        "wait": 0,
    }


def _shopper_visit(market: list[dict] | None, chain: RivalChain, city: str, segments: dict | None, income: dict) -> int:
    """Visit share shoppers would give this door, including an empty city."""
    if market is None or segments is None:
        return 1000
    new = _probe_row(chain, city)
    local = [row for row in market if row.get("city") == city or row.get("id") == "online"]
    mults = visit_multipliers(local + [new], segments, income_index=int(income.get(city, 100)))
    return int(mults.get(str(new["id"]), 1000))


def _loan_visit(market: list[dict] | None, chain: RivalChain, city: str, segments: dict | None, income: dict) -> int:
    """Volume for the loan test.

    A first door with fewer than two neighbors is still a full store, so a city
    the player already occupies can clear the loan. A second door of our own,
    or a city with two neighbors, is scored on the split.
    """
    if market is None or segments is None:
        return 1000
    occupied = sum(1 for store in chain.stores if store.city == city and store.status in {"open", "building"})
    others = sum(
        1
        for row in market
        if row.get("city") == city and row.get("id") != "online" and row.get("chain_id") != chain.chain_id
    )
    if occupied < 1 and others < 2:
        return 1000
    return _shopper_visit(market, chain, city, segments, income)


def _city_appeal(city: str, market: list[dict] | None, income_by_city: dict[str, int] | None) -> tuple:
    """Cheap rank: fewer competitors, then higher income. No year-ahead forecast."""
    income = int((income_by_city or {}).get(city, 100))
    rivals = 0
    if market:
        rivals = sum(1 for row in market if row.get("city") == city and row.get("id") != "online")
    return (-rivals, income)


def _cushion_breaks(chain: RivalChain, equity: int, weekly_opex: int, extra_opex: int, weekly_delta: int) -> bool:
    """True when 52 weeks of this door would put cash under four weeks of costs."""
    cash = chain.cash - equity
    floor = MIN_CASH_WEEKS * max(1, weekly_opex + extra_opex)
    step = chain.last_pnl.net + weekly_delta
    for _ in range(52):
        cash += step
        if cash < floor:
            return True
    return False


def _cannibal(market: list[dict], chain: RivalChain, city: str, segments: dict, income: dict) -> tuple[int, int]:
    own = [row for row in market if row.get("city") == city and row.get("chain_id") == chain.chain_id]
    if not own:
        return 0, 0
    new = _probe_row(chain, city)
    before = chain_sales(market, chain.chain_id, segments, income, 0)
    after = chain_sales(list(market) + [new], chain.chain_id, segments, income, 0)
    stolen = sum(max(0, before.get(str(row["id"]), 0) - after.get(str(row["id"]), 0)) for row in own)
    return stolen, int(after.get(new["id"], 0))


def _consider_open(
    chain: RivalChain,
    personality: Personality,
    memory: ActorMemory,
    *,
    week: int,
    opening_costs: dict[str, int],
    factors: dict | None,
    market: list[dict] | None,
    segments: dict | None,
    income_by_city: dict[str, int] | None,
) -> tuple[Action | None, str]:
    """Return an opening, or the sentence that blocked one."""
    if week < int(chain.cooldowns.get("opening", 0)):
        return None, f"the {OPENING_COOLDOWN_WEEKS}-week opening cooldown is still running"
    if week < int(chain.cooldowns.get("big_call", 0)):
        return None, "the board's cooldown blocked a new store"
    weekly = _weekly_opex(chain, personality, factors)
    cushion = MIN_CASH_WEEKS * weekly
    # Rank by demand, competition and income first. The year-ahead number runs
    # only for that short list, once per city per week.
    appeal: list[tuple[tuple, str, int]] = []
    for city in CITIES:
        cost = int(opening_costs.get(city, 0))
        if cost <= 0:
            continue
        appeal.append((_city_appeal(city, market, income_by_city), city, cost))
    appeal.sort(key=lambda row: (row[0][0], row[0][1], row[1]), reverse=True)
    shortlist = appeal[:5]
    ranked: list[tuple] = []
    blocked = "no city cleared the building rules"
    for _score, city, cost in shortlist:
        equity = cost - int(cost * BUILD_LTV)
        # The cash that leaves is the equity. The growth mandate changes the year-ahead bar, not the sticker.
        insisted = equity
        if chain.cash < cushion + insisted:
            blocked = "cash is under the cushion plus the cash the building needs"
            continue
        income = income_by_city or {}
        loan_visit = _loan_visit(market, chain, city, segments, income)
        shopper_visit = _shopper_visit(market, chain, city, segments, income)
        probe = RivalStore(id=f"probe:{city}", city=city, opened_on=0, status="open", price_index=chain.price_index)
        pnl = store_pnl(
            probe,
            gross_margin_bps=personality.gross_margin_bps,
            opex_bps=personality.opex_bps,
            visit_mult=loan_visit,
            war_intensity=0,
            cost_cut_pct=chain.cost_cut_pct,
            debt_share=0,
            factors=factors,
            shelf_index=personality.price_index,
        )
        shop = pnl if shopper_visit == loan_visit else store_pnl(
            probe,
            gross_margin_bps=personality.gross_margin_bps,
            opex_bps=personality.opex_bps,
            visit_mult=shopper_visit,
            war_intensity=0,
            cost_cut_pct=chain.cost_cut_pct,
            debt_share=0,
            factors=factors,
            shelf_index=personality.price_index,
        )
        incremental = pnl.net
        stolen = 0
        occupied = sum(1 for store in chain.stores if store.city == city and store.status in {"open", "building"})
        if market is not None and segments is not None:
            stolen, fresh = _cannibal(market, chain, city, segments, income_by_city or {})
            if fresh > 0 and stolen / fresh > CANNIBAL_MAX:
                blocked = "the new door would take too much from our own stores"
                continue
            if fresh > 0 and pnl.net > 0:
                incremental = int(round(pnl.net * max(0.0, fresh - stolen) / fresh))
        if len(chain.ebitda_trail) < 13:
            realized = max(0, sum(store_pnl(
                store,
                gross_margin_bps=personality.gross_margin_bps,
                opex_bps=personality.opex_bps,
                visit_mult=1000,
                war_intensity=0,
                cost_cut_pct=chain.cost_cut_pct,
                debt_share=0,
                factors=factors,
                shelf_index=personality.price_index,
            ).net for store in _open_stores(chain))) * 52
        else:
            realized = trailing_ebitda(chain)
        earned = max(0, realized) + max(0, incremental) * 52
        allowed, loan = build_loan_terms(chain, cost, weekly + pnl.opex, incremental, earned)
        if not allowed:
            blocked = "the building loan does not cover"
            continue
        payment = _loan_payment(loan)
        weekly_net = incremental - payment
        if occupied >= 1:
            # A second or third door is judged on the year after the sales it takes
            # from our own stores and the loan it adds. Refuse it if that year
            # would drop the drawer under the cushion.
            delta = weekly_net
            if stolen > 0 and chain.last_pnl.sales > 0 and chain.last_pnl.net > 0:
                delta -= int(stolen * chain.last_pnl.net / chain.last_pnl.sales)
            if _cushion_breaks(chain, equity, weekly, pnl.opex, delta):
                blocked = "the extra door would break the cash cushion"
                continue
        # The bar uses the shoppers' volume, so a crowded city loses to an empty one.
        value = city_forecast(chain.chain_id, week, city, chain.price_index, shop.net, delay=4)
        cover = shop.net - payment
        ranked.append((city, value, cost, loan, equity, cover, int(income.get(city, 100)), occupied, shop.opex))
    if not ranked:
        _remember_block(memory, blocked)
        return None, blocked
    bar = _open_bar(personality)
    pairs = []
    filing: dict[int, bool] = {}
    for city, value, cost, loan, equity, cover, _city_income, occupied, _door_opex in ranked:
        # File only a door that covers its own payment at the shoppers' volume.
        # A loan that clears on a full week still stays on the menu.
        file_it = cover > 0 and value >= bar and occupied < 1
        action = Action(
            actor=_actor(chain),
            kind="open_store",
            args={"city": city, "site_band": 2, "cost": cost, "loan": loan, "equity": equity, "rule": "open"},
        )
        pairs.append((action, float(cover if file_it else 1)))
        filing[id(action)] = file_it
    chosen = argmax(pairs)
    if not filing.get(id(chosen), False):
        blocked = "the year ahead did not clear this chain's bar"
        _remember_block(memory, blocked)
        return None, blocked
    place = str(chosen.args["city"]).replace("_", " ")
    chosen.reason = reason(
        f"{_name(chain)} filed to open in {place}. The next year of that door cleared the bar."
    )
    return chosen, ""


def _consider_close(
    chain: RivalChain,
    personality: Personality,
    *,
    week: int,
    factors: dict | None,
) -> Action | None:
    if week < int(chain.cooldowns.get("big_call", 0)):
        return None
    trail = chain.ebitda_trail
    if len(trail) < 39:
        return None
    quarters = [sum(trail[-39:-26]), sum(trail[-26:-13]), sum(trail[-13:])]
    if any(part >= 0 for part in quarters):
        return None
    open_now = _open_stores(chain)
    for store in open_now:
        pnl = store_pnl(
            store,
            gross_margin_bps=personality.gross_margin_bps,
            opex_bps=personality.opex_bps,
            visit_mult=1000,
            war_intensity=0,
            cost_cut_pct=chain.cost_cut_pct,
            debt_share=0,
            factors=factors,
            shelf_index=personality.price_index,
        )
        ahead = city_forecast(chain.chain_id, week, store.city, store.price_index, pnl.net, delay=0)
        if ahead >= 0:
            continue
        if len(open_now) == 1:
            # Closing the last door wipes a chain that still has its cushion.
            weekly = chain.last_pnl.opex
            if weekly > 0 and chain.cash >= MIN_CASH_WEEKS * weekly:
                continue
            if not last_store_cannot_earn(chain, pnl.net * 13):
                continue
        place = store.city.replace("_", " ")
        return _done(
            chain,
            "close_store",
            {"store_id": store.id, "city": store.city, "rule": "close"},
            f"{_name(chain)} will close its {place} door. It lost three quarters and the next year stays negative.",
        )
    return None


def _price_action(
    chain: RivalChain,
    personality: Personality,
    *,
    share_delta_points: float | None,
    city: str,
) -> Action | None:
    step = _step(personality)
    shelf = personality.price_index
    price = chain.price_index
    drop = _share_drop_points(personality)
    share_falling = share_delta_points is not None and share_delta_points >= drop
    share_steady = share_delta_points is None or share_delta_points <= 0.5
    if share_falling and price - step >= max(86, shelf - 6):
        place = f" in {city.replace('_', ' ')}" if city else ""
        return _done(
            chain,
            "set_chain_price_index",
            {"delta": -step, "rule": "pricing"},
            f"{_name(chain)} cut its basket by {step} points{place} because shoppers shifted away.",
        )
    # A raise stops at the chain's own shelf. Going past it does not fix a thin margin.
    if price < shelf - 1 and (share_steady or price <= shelf - 2):
        raised = min(step, shelf - price)
        if raised <= 0 or clamp_price(price + raised) == price:
            return None
        return _done(
            chain,
            "set_chain_price_index",
            {"delta": raised, "rule": "pricing"},
            f"{_name(chain)} raised its basket by {raised} points because the margin is under the plan.",
        )
    return None


def _promo_action(chain: RivalChain, personality: Personality, *, week: int, city: str, falling: bool) -> Action | None:
    stores = [store for store in _open_stores(chain) if not city or store.city == city]
    if not stores:
        stores = _open_stores(chain)
    if not stores:
        return None
    target = stores[0]
    if target.promo_depth >= 10 and target.promo_until_week >= week:
        return None
    depth = 20 if _peak(week) or falling or _step(personality) == 4 else 10
    place = target.city.replace("_", " ")
    why = "shoppers are leaving" if falling else "the season peak is here" if _peak(week) else "the calendar calls for a push"
    return _done(
        chain,
        "promo",
        {"city": target.city, "dept": target.focus_dept or "grocery", "depth": depth, "weeks": 2, "rule": "promo"},
        f"{_name(chain)} is promoting {place} at {depth}% off because {why}.",
    )


def _shelf_action(chain: RivalChain, *, city: str, segments: dict | None, income: int, stockouts: bool) -> Action | None:
    stores = _open_stores(chain)
    if not stores:
        return None
    target = next((store for store in stores if store.city == city), stores[0])
    dept = _preferred_dept(segments, income)
    place = target.city.replace("_", " ")
    if stockouts:
        text = f"{_name(chain)} restocked {place} before moving the shelf."
    else:
        text = f"{_name(chain)} gave more of the {place} shelf to {dept.replace('_', ' ')}."
    return _done(
        chain,
        "copy_best_seller",
        {"city": target.city, "dept": dept, "rule": "planogram"},
        text,
    )


def _checkout_wait(store: RivalStore) -> int:
    return {"lean": 2, "normal": 0, "heavy": -1}.get(store.staffing, 0)


def _staff_action(chain: RivalChain, memory: ActorMemory) -> Action | None:
    """Add staff only when waits or stockouts rise. Cut only after eight down weeks."""
    stores = _open_stores(chain)
    if not stores:
        return None
    stockouts = sum(store.stockouts for store in stores)
    wait = max(_checkout_wait(store) for store in stores)
    previous_stock = int(memory.counters.get("prev_stockouts", stockouts))
    previous_wait = int(memory.counters.get("prev_wait", wait))
    memory.counters["prev_stockouts"] = stockouts
    memory.counters["prev_wait"] = wait
    down = int(memory.counters.get("sales_down_weeks", 0))
    if stockouts > previous_stock or wait > previous_wait:
        needy = [store for store in stores if store.stockouts > 0 or _checkout_wait(store) > previous_wait]
        store = needy[0] if needy else stores[0]
        if store.staffing == "heavy":
            return None
        why = "shelves are running short" if stockouts > previous_stock else "the checkout line got longer"
        place = store.city.replace("_", " ")
        return _done(
            chain,
            "set_staffing",
            {"store_id": store.id, "city": store.city, "level": "heavy", "rule": "staffing"},
            f"{_name(chain)} added staff in {place} because {why}.",
        )
    if down >= 8:
        store = min(stores, key=lambda item: (item.weekly_sales, item.id))
        if store.staffing == "lean":
            return None
        place = store.city.replace("_", " ")
        return _done(
            chain,
            "set_staffing",
            {"store_id": store.id, "city": store.city, "level": "lean", "rule": "staffing"},
            f"{_name(chain)} cut staff in {place} because sales have been down for eight weeks.",
        )
    return None


def _since(memory: ActorMemory, kind: str, week: int) -> int:
    last = int(memory.counters.get(f"last:{kind}", -100))
    return week - last


def _mark(memory: ActorMemory, action: Action, week: int) -> Action:
    memory.counters[f"last:{action.kind}"] = week
    if action.kind == "set_chain_price_index" and int(action.args.get("delta", 0)) < 0:
        memory.counters["last:price_cut"] = week
    return action


def _cut_age(memory: ActorMemory, week: int) -> int:
    return week - int(memory.counters.get("last:price_cut", -100))


def choose_by_rules(
    chain: RivalChain,
    personality: Personality,
    memory: ActorMemory,
    *,
    week: int,
    opening_costs: dict[str, int] | None = None,
    factors: dict[str, int] | None = None,
    market: list[dict] | None = None,
    segments: dict | None = None,
    income_by_city: dict[str, int] | None = None,
    wars: dict[str, int] | None = None,
) -> Action:
    del wars
    name = _name(chain)
    if chain.cash < 0 and chain.revolver_debt < chain.credit_line:
        room = chain.credit_line - chain.revolver_debt
        amount = min(2_000_000, room)
        return _done(
            chain,
            "raise_capital",
            {"amount": amount, "rule": "cash"},
            f"{name} drew ${amount // 1_000_000}M because the drawer is empty.",
        )
    weekly_cost = chain.last_pnl.opex
    # Top up once, to eight weeks, when the drawer slips under five. A draw that
    # only fills the four-week floor is spent by the time the week settles.
    if weekly_cost > 0 and chain.cash < 5 * weekly_cost and chain.revolver_debt < chain.credit_line:
        room = chain.credit_line - chain.revolver_debt
        amount = min(room, max(0, 8 * weekly_cost - chain.cash))
        if amount > 0:
            draw = _done(
                chain,
                "raise_capital",
                {"amount": amount, "rule": "cash"},
                f"{name} drew ${amount:,} so four weeks of costs stay in the drawer.",
            )
            if not board_blocks(chain, draw):
                return draw

    sales = chain.last_pnl.sales
    previous = int(memory.counters.get("prev_sales", sales))
    if sales < previous and previous > 0:
        memory.counters["sales_down_weeks"] = int(memory.counters.get("sales_down_weeks", 0)) + 1
    else:
        memory.counters["sales_down_weeks"] = 0
    memory.counters["prev_sales"] = sales

    share_delta = None
    watched = ""
    if market is not None and segments is not None:
        worst = None
        for store in _open_stores(chain):
            income = int((income_by_city or {}).get(store.city, 100))
            bps = _city_share_bps(market, chain, store.city, segments, income)
            if bps is None:
                continue
            old = _note_share(memory, store.city, bps)
            if old is None:
                continue
            drop = (old - bps) / 100.0
            if worst is None or drop > worst:
                worst = drop
                watched = store.city
        share_delta = worst

    falling = share_delta is not None and share_delta >= _share_drop_points(personality)
    city = watched or (_open_stores(chain)[0].city if _open_stores(chain) else "")
    income = int((income_by_city or {}).get(city, 100))

    # A real share loss can cut the ticket, and only once in eight weeks.
    # The first filing happens at the shelf price, so a cut waits out the opening cooldown.
    priced = None
    cooldown_done = week >= int(chain.cooldowns.get("opening", 0))
    if falling and cooldown_done and _since(memory, "set_chain_price_index", week) >= 8:
        priced = _price_action(chain, personality, share_delta_points=share_delta, city=city)
    stockouts = any(store.stockouts > 0 for store in _open_stores(chain))
    if stockouts:
        fixed = _shelf_action(chain, city=city, segments=segments, income=income, stockouts=True)
        if fixed is not None:
            return _mark(memory, fixed, week)

    opened, block = _consider_open(
        chain,
        personality,
        memory,
        week=week,
        opening_costs=opening_costs or {},
        factors=factors,
        market=market,
        segments=segments,
        income_by_city=income_by_city,
    )
    if opened is not None:
        return _mark(memory, opened, week)

    closed = _consider_close(chain, personality, week=week, factors=factors)
    if closed is not None:
        return _mark(memory, closed, week)

    if priced is not None:
        return _mark(memory, priced, week)
    # A cut has to stand. Raising straight back to the shelf would undo it.
    if _cut_age(memory, week) >= 13 and _since(memory, "set_chain_price_index", week) >= 4 and chain.price_index <= personality.price_index - 2:
        repair = _price_action(chain, personality, share_delta_points=None, city=city)
        if repair is not None:
            return _mark(memory, repair, week)

    sales_ok = chain.last_pnl.sales <= 0 or chain.last_pnl.net * 10_000 >= (chain.mandate.target_net_margin_bps // 2) * chain.last_pnl.sales
    ready: list[Action] = []
    if _cut_age(memory, week) >= 13 and _since(memory, "set_chain_price_index", week) >= 8:
        # A margin that is already short gets a raise on its own week, not every week.
        repair = _price_action(chain, personality, share_delta_points=None, city=city)
        if repair is not None:
            ready.append(repair)
    # A promo that is still on in week 12, 25, 38, or 51 is the week the board reads.
    board_week = week % 13 in {11, 12}
    if sales_ok and not board_week and _since(memory, "promo", week) >= 1:
        promo_move = _promo_action(chain, personality, week=week, city=city, falling=falling)
        if promo_move is not None:
            ready.append(promo_move)
    staff_move = _staff_action(chain, memory)
    if staff_move is not None and _since(memory, "set_staffing", week) >= 1:
        ready.append(staff_move)
    # The basket is already at the shelf and the margin is still short. Trim
    # costs instead of hiring a crew that the week did not ask for.
    margin_short = chain.last_pnl.sales > 0 and chain.last_pnl.net * 10_000 < chain.mandate.target_net_margin_bps * chain.last_pnl.sales
    if margin_short and _since(memory, "cut_costs", week) >= 1:
        ready.append(
            _done(
                chain,
                "cut_costs",
                {"pct": 2, "rule": "margin"},
                f"{name} trimmed store costs by 2% because the margin is under the plan.",
            )
        )
    if _since(memory, "copy_best_seller", week) >= 1:
        shelf_move = _shelf_action(chain, city=city, segments=segments, income=income, stockouts=False)
        if shelf_move is not None:
            ready.append(shelf_move)
    if ready:
        action = ready[week % len(ready)]
    else:
        action = _done(chain, "do_nothing", {"rule": "none"}, f"{name} held because no rule fired.")
    action = _mark(memory, action, week)
    if block:
        extra = f" No new door: {block}."
        combined = action.reason + extra
        if len(combined) > 160:
            combined = (action.reason[: 157 - len(extra)] + "... " + extra).strip()
        action.reason = reason(combined[:160])
    return action
