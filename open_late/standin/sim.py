"""Deterministic stand-in for the game.

This is not the corporate sim. It exists so the AI can be initialized, stepped,
and checked without that game. Costs here are local defaults, passed into the
minds through the snapshot, and the same numbers are used when an action is
applied.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from open_late.ai.constants import (
    CITIES,
    LOG_WEEKS,
    SUPPLIERS,
    week_of,
)
from open_late.ai.forecast import card_units, store_pnl
from open_late.ai.legal import clamp_price, stamp_cooldowns
from open_late.ai.models import (
    Action,
    ActionResult,
    ChainPnL,
    GameEvent,
    LogRow,
    RivalStore,
)
from open_late.ai.observation import national_factors
from open_late.ai.provider import RetailAI
from open_late.ai.snapshot import Snapshot

OPENING_COST = 6_000_000
REMODEL_COST = 500_000
RAISE_AMOUNT = 2_000_000


@dataclass
class SimResult:
    seed: int
    difficulty: str
    weeks: int
    actions: list[str] = field(default_factory=list)
    final_cash: dict[str, int] = field(default_factory=dict)
    nets: dict[str, int] = field(default_factory=dict)
    sales: dict[str, int] = field(default_factory=dict)
    player_sales: int = 0
    kinds_by_archetype: dict[str, list[str]] = field(default_factory=dict)
    reasons_ok: bool = True

    @property
    def signature(self) -> str:
        payload = {
            "actions": self.actions,
            "cash": self.final_cash,
            "nets": self.nets,
        }
        return repr(payload)


def make_snapshot(
    seed: int,
    *,
    difficulty: str = "standard",
    player_chain: str = "megamart",
    ai_enabled: bool = True,
    provider: RetailAI | None = None,
    personalities: dict | None = None,
) -> tuple[Snapshot, RetailAI]:
    provider = provider or RetailAI(personalities=personalities)
    factors = national_factors(100)
    factors["95"] = 100
    snap = Snapshot(
        seed=seed,
        day=1,
        week=1,
        difficulty=difficulty,
        ai_enabled=ai_enabled,
        player_chain_id=player_chain,
        opening_cost=OPENING_COST,
        remodel_cost=REMODEL_COST,
        raise_amount=RAISE_AMOUNT,
        factors=factors,
        public={
            "player_price_index": {city: 100 for city in CITIES},
            "player_weekly_sales": {"evansville": 1_800_000},
            "player_store_cities": {"evansville": "evansville"},
            "player_stores": [
                {
                    "id": "evansville",
                    "city": "evansville",
                    "opened_on": 1,
                    "distance_band": 1,
                    "trust": 60,
                    "focus": "grocery",
                    "promo": 0,
                    "stockouts": 0,
                }
            ],
            "campaigns": [],
            "permits": [],
            "news_ids": [],
            "war_until": {},
        },
        northline={
            "name": "Northline Market",
            "price_index": 102,
            "reputation": 38,
            "blocks_away": 8,
            "focus": "grocery",
            "heat": 0,
            "city": "evansville",
            "note": "",
        },
        hidden={"player_cash": 1_350_000, "player_weekly_net": 20_000, "stockouts": [], "orders": 0},
    )
    snap.ai = provider.init_world(snap)
    snap.accounts = _accounts(snap)
    return snap, provider


def _accounts(snap: Snapshot) -> dict[str, list[dict]]:
    buyers = [{"buyer_id": "player", "relationship": 42, "volume": 200, "terms": "cash"}]
    if snap.ai is not None:
        for chain_id in sorted(snap.ai.chains):
            buyers.append({"buyer_id": chain_id, "relationship": 42, "volume": 200, "terms": "cash"})
    accounts = {}
    for supplier_id, _name, _dept in SUPPLIERS:
        if supplier_id == "labelco":
            continue
        accounts[supplier_id] = [dict(row) for row in buyers]
    return accounts


def apply_actions(snap: Snapshot, actions: list[Action]) -> list[ActionResult]:
    results: list[ActionResult] = []
    for action in actions:
        result = _apply_one(snap, action)
        results.append(result)
        if snap.ai is not None:
            _append_log(snap, action, result)
    return results


def _append_log(snap: Snapshot, action: Action, result: ActionResult) -> None:
    assert snap.ai is not None
    snap.ai.log.append(LogRow(day=snap.day, week=snap.week, action=action, result=result))
    floor = snap.week - (LOG_WEEKS - 1)
    snap.ai.log = [row for row in snap.ai.log if row.week >= floor]


def _apply_one(snap: Snapshot, action: Action) -> ActionResult:
    kind = action.kind
    if snap.ai is None:
        return ActionResult(action=action, accepted=False, note="ai off")
    chain = _chain_for(snap, action)
    if kind == "do_nothing" or kind == "hold":
        return ActionResult(action=action, accepted=True, note="ok")
    if kind == "set_chain_price_index" and chain is not None:
        delta = int(action.args.get("delta", 0))
        if delta < -6 or delta > 6 or chain.status == "bankrupt":
            return ActionResult(action=action, accepted=False, note="rejected: price")
        chain.price_index = clamp_price(chain.price_index + delta)
        for store in chain.stores:
            store.price_index = clamp_price(store.price_index + delta)
        return ActionResult(action=action, accepted=True, note="ok")
    if kind == "open_store" and chain is not None:
        cost = int(action.args.get("cost", snap.opening_cost))
        room = chain.cash + max(0, chain.credit_line - chain.debt)
        if room < cost or chain.status == "bankrupt":
            return ActionResult(action=action, accepted=False, note="rejected: cash")
        city = str(action.args["city"])
        chain.cash -= cost
        existing = [store for store in chain.stores if store.city == city]
        store = RivalStore(
            id=f"store:{chain.chain_id}:{city}:{len(existing) + 1}",
            city=city,
            opened_on=snap.day + 14,
            status="building",
            distance_band=int(action.args.get("site_band", 2)),
            price_index=chain.price_index,
            focus_dept="grocery",
        )
        chain.stores.append(store)
        stamp_cooldowns(chain, action, snap.week)
        snap.public["permits"].append(
            {"applicant": chain.chain_id, "city": city, "filed_day": snap.day}
        )
        return ActionResult(action=action, accepted=True, note="ok")
    if kind == "close_store" and chain is not None:
        store = _store(chain, str(action.args.get("store_id", "")))
        if store is None or store.status != "open":
            return ActionResult(action=action, accepted=False, note="rejected: store")
        store.status = "closed"
        stamp_cooldowns(chain, action, snap.week)
        return ActionResult(action=action, accepted=True, note="ok")
    if kind == "remodel" and chain is not None:
        cost = int(action.args.get("cost", snap.remodel_cost))
        if chain.cash < cost:
            return ActionResult(action=action, accepted=False, note="rejected: cash")
        chain.cash -= cost
        return ActionResult(action=action, accepted=True, note="ok")
    if kind == "start_price_war" and chain is not None:
        city = str(action.args["city"])
        intensity = int(action.args.get("intensity", 8))
        weeks = int(action.args.get("weeks", 4))
        if intensity < 4 or intensity > 12 or weeks < 2 or weeks > 8:
            return ActionResult(action=action, accepted=False, note="rejected: war")
        snap.wars[city] = intensity
        snap.public["war_until"][city] = snap.week + weeks - 1
        stamp_cooldowns(chain, action, snap.week)
        return ActionResult(action=action, accepted=True, note="ok")
    if kind == "end_price_war":
        city = str(action.args.get("city", ""))
        snap.wars[city] = 0
        snap.public["war_until"][city] = snap.week - 1
        return ActionResult(action=action, accepted=True, note="ok")
    if kind == "promo" and chain is not None:
        city = str(action.args["city"])
        depth = int(action.args.get("depth", 20))
        weeks = int(action.args.get("weeks", 2))
        for store in chain.stores:
            if store.city == city and store.status == "open":
                store.promo_depth = depth
                store.promo_until_week = snap.week + weeks - 1
        return ActionResult(action=action, accepted=True, note="ok")
    if kind == "copy_best_seller" and chain is not None:
        city = str(action.args.get("city", ""))
        dept = str(action.args.get("dept", "grocery"))
        for store in chain.stores:
            if store.city == city and store.status == "open":
                store.focus_dept = dept
        return ActionResult(action=action, accepted=True, note="ok")
    if kind == "cut_costs" and chain is not None:
        chain.cost_cut_pct = int(action.args.get("pct", 1))
        chain.cost_cut_until_week = snap.week + 8
        return ActionResult(action=action, accepted=True, note="ok")
    if kind == "defend" and chain is not None:
        city = str(action.args.get("city", ""))
        match = clamp_price(int(action.args.get("match_index", chain.price_index)))
        for store in chain.stores:
            if store.city == city and store.status == "open":
                store.price_index = match
                store.focus_dept = str(action.args.get("dept", store.focus_dept))
        return ActionResult(action=action, accepted=True, note="ok")
    if kind == "raise_capital" and chain is not None:
        amount = int(action.args.get("amount", 0))
        if chain.debt + amount > chain.credit_line:
            return ActionResult(action=action, accepted=False, note="rejected: credit")
        chain.cash += amount
        chain.debt += amount
        stamp_cooldowns(chain, action, snap.week)
        return ActionResult(action=action, accepted=True, note="ok")
    if kind == "pay_down_debt" and chain is not None:
        amount = int(action.args.get("amount", 0))
        if amount > chain.cash or amount > chain.debt:
            return ActionResult(action=action, accepted=False, note="rejected: cash")
        chain.cash -= amount
        chain.debt -= amount
        return ActionResult(action=action, accepted=True, note="ok")
    if kind == "set_mandate" and chain is not None:
        chain.mandate.target_net_margin_bps = int(action.args.get("target_net_margin_bps", 200))
        chain.mandate.capex_budget = int(action.args.get("capex_budget", chain.mandate.capex_budget))
        chain.mandate.max_debt_ratio_x100 = int(
            action.args.get("max_debt_ratio_x100", chain.mandate.max_debt_ratio_x100)
        )
        chain.mandate.growth_vs_profit = int(action.args.get("growth_vs_profit", chain.mandate.growth_vs_profit))
        if int(action.args.get("restore_active", 0)) == 1 and chain.cash >= 0 and chain.status == "distressed":
            chain.status = "active"
        return ActionResult(action=action, accepted=True, note="ok")
    if kind == "replace_ceo" and chain is not None:
        chain.personality_id = str(action.args.get("personality_id", chain.personality_id))
        return ActionResult(action=action, accepted=True, note="ok")
    if kind == "declare_distress" and chain is not None:
        chain.status = "distressed"
        return ActionResult(action=action, accepted=True, note="ok")
    if kind == "file_bankruptcy" and chain is not None:
        chain.status = "bankrupt"
        chain.bankrupt_on = snap.day
        for store in chain.stores:
            if store.status != "closed":
                store.status = "closed"
        return ActionResult(action=action, accepted=True, note="ok")
    if kind == "set_local_price" and chain is not None:
        store = _store(chain, str(action.args.get("store_id", "")))
        if store is None:
            return ActionResult(action=action, accepted=False, note="rejected: store")
        delta = int(action.args.get("delta", 0))
        raw = store.price_index + delta
        bounded = min(chain.price_index + 3, max(chain.price_index - 3, raw))
        bounded = clamp_price(bounded)
        clamped = {"price_index": bounded} if bounded != raw else None
        store.price_index = bounded
        return ActionResult(action=action, accepted=True, clamped=clamped, note="ok")
    if kind in {"set_focus", "set_staffing", "request_promo", "markdown"} and chain is not None:
        store = _store(chain, str(action.args.get("store_id", "")))
        if store is None:
            return ActionResult(action=action, accepted=False, note="rejected: store")
        if kind == "set_focus":
            store.focus_dept = str(action.args.get("dept", store.focus_dept))
        elif kind == "set_staffing":
            store.staffing = str(action.args.get("level", "normal"))
        elif kind == "markdown":
            store.price_index = clamp_price(store.price_index - 2)
        return ActionResult(action=action, accepted=True, note="ok")
    if kind == "adjust_cost":
        quote = _quote(snap, action)
        if quote is not None:
            quote.cost_index = int(action.args.get("cost_index", quote.cost_index))
        return ActionResult(action=action, accepted=True, note="ok")
    if kind == "allocate":
        quote = _quote(snap, action)
        if quote is not None:
            quote.allocation_bps = {str(k): int(v) for k, v in dict(action.args.get("allocation_bps", {})).items()}
        return ActionResult(action=action, accepted=True, note="ok")
    if kind == "quote_lead_time":
        quote = _quote(snap, action)
        if quote is not None:
            quote.lead_time_days = int(action.args.get("lead_time_days", quote.lead_time_days))
        return ActionResult(action=action, accepted=True, note="ok")
    if kind == "offer_terms":
        quote = _quote(snap, action)
        offers = {str(k): str(v) for k, v in dict(action.args.get("terms_offer", {})).items()}
        if quote is not None:
            quote.terms_offer = offers
        supplier_id = action.actor.id.split(":", 1)[-1]
        for row in snap.accounts.get(supplier_id, []):
            buyer = str(row["buyer_id"])
            if buyer in offers:
                row["terms"] = offers[buyer]
        return ActionResult(action=action, accepted=True, note="ok")
    if kind == "permit":
        if action.args.get("result") == "deny":
            return ActionResult(action=action, accepted=False, note="rejected: deny")
        weeks = int(action.args.get("weeks", 2))
        applicant = str(action.args.get("applicant", ""))
        city = str(action.args.get("city", ""))
        chain = snap.ai.chains.get(applicant)
        if chain is not None:
            for store in chain.stores:
                if store.city == city and store.status == "building":
                    store.opened_on = snap.day + weeks * 7
        snap.public["permits"] = [
            row
            for row in snap.public.get("permits", [])
            if not (row.get("applicant") == applicant and row.get("city") == city)
        ]
        return ActionResult(action=action, accepted=True, note="ok")
    if kind in {
        "schedule_road_work",
        "sales_tax_drift",
        "propose_wage_floor",
        "set_fair_schedule",
        "schedule_inspection",
        "set_bag_rule",
    }:
        if snap.ai is not None:
            snap.ai.permits[str(action.args.get("factor_id", kind))] = int(action.args.get("delta", 0))
        return ActionResult(action=action, accepted=True, note="ok")
    if kind == "set_price_index":
        snap.northline["price_index"] = clamp_price(
            int(action.args.get("price_index", snap.northline.get("price_index", 102))), 86, 120
        )
        return ActionResult(action=action, accepted=True, note="ok")
    if kind == "set_blocks":
        blocks = max(3, int(action.args.get("blocks_away", 8)))
        snap.northline["blocks_away"] = blocks
        return ActionResult(action=action, accepted=True, note="ok")
    if kind == "invest_reputation":
        snap.northline["reputation"] = min(100, int(action.args.get("reputation", 39)))
        return ActionResult(action=action, accepted=True, note="ok")
    return ActionResult(action=action, accepted=False, note=f"rejected: {kind}")


def settle(snap: Snapshot) -> None:
    """Open finished builds and post one week of integer P&L."""
    if snap.ai is None or not snap.ai.enabled:
        return
    card = snap.ai.shopper_card
    for chain in snap.ai.chains.values():
        for store in chain.stores:
            if store.status == "building" and store.opened_on <= snap.day:
                store.status = "open"
        person = snap.ai.personalities.get(chain.personality_id)
        if person is None or chain.status == "bankrupt":
            continue
        open_stores = [store for store in chain.stores if store.status == "open"]
        if not open_stores:
            chain.last_pnl = ChainPnL(week=snap.week)
            continue
        sales = cogs = opex = net = 0
        debt_share = chain.debt // len(open_stores)
        cut = chain.cost_cut_pct if snap.week <= chain.cost_cut_until_week else 0
        for store in open_stores:
            if store.promo_until_week and snap.week > store.promo_until_week:
                store.promo_depth = 0
            intensity = _intensity(snap, store.city)
            mult = 1000
            if card is not None:
                mult = card.visit_mult.get(store.id, 1000)
            pnl = store_pnl(
                store,
                gross_margin_bps=person.gross_margin_bps,
                opex_bps=person.opex_bps,
                visit_mult=mult,
                war_intensity=intensity,
                cost_cut_pct=cut,
                debt_share=debt_share,
            )
            store.weekly_sales = pnl.sales
            sales += pnl.sales
            cogs += pnl.cogs
            opex += pnl.opex
            net += pnl.net
        chain.cash += net
        chain.last_pnl = ChainPnL(week=snap.week, sales=sales, cogs=cogs, opex=opex, net=net)
    _settle_player(snap)


def _settle_player(snap: Snapshot) -> None:
    card = snap.ai.shopper_card if snap.ai is not None else None
    sales_out: dict[str, int] = {}
    for row in snap.public.get("player_stores") or []:
        city = str(row["city"])
        price = int(snap.public["player_price_index"].get(city, 100))
        price = max(1, price - _intensity(snap, city) // 2)
        mult = 1000
        if card is not None:
            mult = card.visit_mult.get(str(row["id"]), 1000)
        sales_out[str(row["id"])] = int(round(card_units(mult, 0) * price / 100.0))
    snap.public["player_weekly_sales"] = sales_out


def _intensity(snap: Snapshot, city: str) -> int:
    until = int(snap.public.get("war_until", {}).get(city, 0))
    if snap.week <= until:
        return int(snap.wars.get(city, 0))
    return 0


def simulate(
    seed: int,
    *,
    weeks: int = 4,
    difficulty: str = "standard",
    player_style: str = "passive",
    ai_enabled: bool = True,
    personalities: dict | None = None,
) -> SimResult:
    snap, provider = make_snapshot(
        seed, difficulty=difficulty, ai_enabled=ai_enabled, personalities=personalities
    )
    taken: list[str] = []
    ceo_kinds: dict[str, list[str]] = {}
    reasons_ok = True
    for _ in range(weeks):
        inflation = int(snap.factors.get("95", 100))
        snap.opening_cost = int(round(OPENING_COST * inflation / 100))
        actions = provider.weekly(snap) if ai_enabled and difficulty != "off" else []
        for action in actions:
            if not action.reason or len(action.reason) > 160:
                reasons_ok = False
            taken.append(f"{snap.week}:{action.actor.id}:{action.kind}")
            if action.actor.kind == "ceo":
                chain_id = action.actor.id.split(":", 1)[1]
                ceo_kinds.setdefault(chain_id, []).append(action.kind)
        apply_actions(snap, actions)
        if ai_enabled and difficulty != "off":
            provider.shopper_card(snap)
        else:
            provider.shopper_card(snap)
        settle(snap)
        _player_step(snap, provider, player_style)
        snap.day += 7
        snap.week = week_of(snap.day)
    cash = {}
    nets = {}
    sales = {}
    kinds: dict[str, list[str]] = {}
    if snap.ai is not None:
        for chain_id, chain in sorted(snap.ai.chains.items()):
            cash[chain_id] = chain.cash
            nets[chain_id] = chain.last_pnl.net
            sales[chain_id] = chain.last_pnl.sales
            person = snap.ai.personalities.get(chain.personality_id)
            if person is None:
                continue
            kinds.setdefault(person.archetype, []).extend(ceo_kinds.get(chain_id, []))
    player_sales = sum(int(value) for value in (snap.public.get("player_weekly_sales") or {}).values())
    return SimResult(
        seed=seed,
        difficulty=difficulty,
        weeks=weeks,
        actions=taken,
        final_cash=cash,
        nets=nets,
        sales=sales,
        player_sales=player_sales,
        kinds_by_archetype=kinds,
        reasons_ok=reasons_ok,
    )


def _player_step(snap: Snapshot, provider: RetailAI, style: str) -> None:
    if style == "price_cutter" and snap.week % 2 == 0:
        for city in CITIES:
            current = int(snap.public["player_price_index"][city])
            snap.public["player_price_index"][city] = max(86, current - 4)
            provider.on_event(
                snap,
                GameEvent(
                    name="PlayerBasketIndex",
                    day=snap.day,
                    week=snap.week,
                    city=city,
                    payload={"index": snap.public["player_price_index"][city]},
                ),
            )
    elif style == "expander" and snap.week == 3:
        city = "houston"
        if not any(row.get("city") == city for row in snap.public["player_stores"]):
            snap.public["player_stores"].append(
                {
                    "id": "houston",
                    "city": city,
                    "opened_on": snap.day,
                    "distance_band": 1,
                    "trust": 60,
                    "focus": "grocery",
                    "promo": 0,
                    "stockouts": 0,
                }
            )
            snap.public["player_store_cities"]["houston"] = city
            snap.public["player_price_index"].setdefault(city, 100)
            provider.on_event(
                snap,
                GameEvent(
                    name="PlayerStoreOpened",
                    day=snap.day,
                    week=snap.week,
                    city=city,
                    store_id="houston",
                    payload={},
                ),
            )


def _chain_for(snap: Snapshot, action: Action):
    if snap.ai is None:
        return None
    actor_id = action.actor.id
    if actor_id.startswith("ceo:"):
        return snap.ai.chains.get(actor_id.split(":", 1)[1])
    if actor_id.startswith("board:"):
        return snap.ai.chains.get(actor_id.split(":", 1)[1])
    if actor_id.startswith("store:"):
        chain_id = actor_id.split(":")[1]
        return snap.ai.chains.get(chain_id)
    return None


def _store(chain, store_id: str):
    return next((store for store in chain.stores if store.id == store_id), None)


def _quote(snap: Snapshot, action: Action):
    if snap.ai is None:
        return None
    supplier_id = action.actor.id.split(":", 1)[-1]
    return snap.ai.supplier_quotes.get(supplier_id)
