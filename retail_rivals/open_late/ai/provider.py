"""AIProvider implementation.

``weekly`` returns actions and writes only actor memory. The stand-in (or,
later, the game) is the only economy mutator.
"""

from __future__ import annotations

from open_late.ai.actors.advisor import AdvisorBriefing, compose_advice
from open_late.ai.actors.ceo import choose_ceo_action
from open_late.ai.actors.others import (
    board_actions,
    choose_manager_action,
    choose_northline,
    supplier_actions,
    town_actions,
)
from open_late.ai.context import WeekContext
from open_late.ai.costs import opening_cost_table, traffic_mult
from open_late.ai.constants import (
    CHAIN_COUNTS,
    CHAINS,
    CITIES,
    DEPT_COMMODITY,
    DIFFICULTIES,
    SUPPLIERS,
    chain_logo,
    chain_name,
    factor_key,
)
from open_late.ai.legal import clamp_price
from open_late.ai.memory import add_grudge, append_move, decay_grudge, ensure_memory, update_belief
from open_late.ai.models import (
    AIState,
    Action,
    ActorRef,
    GameEvent,
    Mandate,
    RivalChain,
    RivalStore,
    SupplierQuote,
)
from open_late.ai.observation import build_observation, cash_band
from open_late.ai.personalities import load_personalities, resolve_personalities
from open_late.ai.rng import ai_rng
from open_late.ai.shoppers import bake_card, load_segments
from open_late.ai.snapshot import Snapshot

_ARCHETYPE_BY_SLOT = ("price_leader", "premium", "expander")
_GROWTH = {"price_leader": 35, "premium": 20, "expander": 80}


class RetailAI:
    api_version = 1

    def __init__(self, personalities: dict | None = None) -> None:
        loaded, digest = load_personalities()
        self.weights_hash = digest
        if personalities is None:
            self.personalities = loaded
        else:
            self.personalities = {key: person.model_copy(deep=True) for key, person in personalities.items()}
        self.segments = load_segments()

    def init_world(self, snap: Snapshot, rng: object = None) -> AIState:
        """Build AI state. ``rng`` is ignored so an engine RNG cannot leak in."""
        del rng
        if snap.difficulty not in DIFFICULTIES:
            raise ValueError(f"unknown difficulty {snap.difficulty!r}")
        if not _live(snap):
            return AIState(enabled=False, api_version=self.api_version, weights_hash=self.weights_hash)
        roster = _shuffle_chains(snap.seed, snap.player_chain_id)
        state = AIState(
            enabled=True,
            api_version=self.api_version,
            weights_hash=self.weights_hash,
            roster=roster,
            personalities={key: person.model_copy(deep=True) for key, person in self.personalities.items()},
        )
        _materialize(snap, state)
        _seed_prices(snap, state)
        count = CHAIN_COUNTS[snap.difficulty]
        snap.public["rivals"] = [
            {"id": chain_id, "name": chain_name(chain_id), "logo": chain_logo(chain_id)}
            for chain_id in roster[:count]
        ]
        for supplier_id, _name, _dept in SUPPLIERS:
            if supplier_id == "labelco" and not snap.private_label:
                continue
            state.supplier_quotes[supplier_id] = SupplierQuote(supplier_id=supplier_id)
        return state

    def weekly(self, snap: Snapshot, rng: object = None) -> list[Action]:
        del rng
        if snap.difficulty not in DIFFICULTIES:
            raise ValueError(f"unknown difficulty {snap.difficulty!r}")
        if not _live(snap) or snap.ai is None or not snap.ai.enabled:
            return []
        state = snap.ai
        people, _warning = resolve_personalities(
            state.personalities, self.personalities, state.weights_hash, self.weights_hash
        )
        state.personalities = people
        _materialize(snap, state)
        for chain_id in state.roster:
            ai_rng(snap.seed, "ai.ceo", snap.week, chain_id, "gate").random()
            ai_rng(snap.seed, "ai.board", snap.week, chain_id, "gate").random()

        actions: list[Action] = []
        acting = _acting(snap)
        week_ctx = WeekContext(
            week=snap.week,
            factors=snap.factors,
            opening_costs=opening_cost_table(snap.factors),
            income_by_city={
                city: int(snap.factors.get(factor_key(14, city), snap.factors.get("14", 100))) for city in CITIES
            },
            market=_market_stores(snap),
            segments=self.segments,
        )
        for chain_id in acting:
            chain = state.chains[chain_id]
            person = state.personalities[chain.personality_id]
            board_memory = ensure_memory(state.memories, f"board:{chain_id}")
            actions.extend(
                board_actions(
                    chain,
                    board_memory,
                    person,
                    seed=snap.seed,
                    week=snap.week,
                    personalities=state.personalities,
                    factors=week_ctx.factors,
                    opening_costs=week_ctx.opening_costs,
                )
            )
        for chain_id in acting:
            chain = state.chains[chain_id]
            if chain.status == "bankrupt":
                continue
            person = state.personalities[chain.personality_id]
            memory = ensure_memory(state.memories, f"ceo:{chain_id}")
            decay_grudge(memory, person.grudge_decay, snap.week)
            cities = {store.city for store in chain.stores if store.status in {"open", "building"}}
            observation = _observe(snap, ActorRef(kind="ceo", id=f"ceo:{chain_id}"), cities, _own_chain(chain))
            prices = {city: int(index) for city, index in observation.public.get("player_price_index", {}).items()}
            chosen = choose_ceo_action(
                chain,
                person,
                memory,
                seed=snap.seed,
                week=snap.week,
                difficulty=snap.difficulty,
                opening_cost=snap.opening_cost,
                wars=dict(snap.wars),
                player_price=prices,
                visit_mult=_visit_mult(state, chain),
                remodel_cost=snap.remodel_cost,
                raise_amount=snap.raise_amount,
                context=week_ctx,
            )
            if _board_vetoes(chain, chosen):
                veto = Action(
                    actor=ActorRef(kind="board", id=f"board:{chain_id}"),
                    kind="approve_or_veto",
                    args={"verdict": "veto", "kind": chosen.kind, "city": str(chosen.args.get("city", ""))},
                )
                veto.reason = f"The board vetoed the {chosen.kind.replace('_', ' ')}."
                actions.append(veto)
                chosen = Action(actor=chosen.actor, kind="do_nothing", args={})
                chosen.reason = f"The {chain_id} chief executive held after the board's veto."
            actions.append(chosen)
            append_move(
                memory,
                {
                    "week": snap.week,
                    "kind": chosen.kind,
                    "city": str(chosen.args.get("city", "")),
                    "delta": int(chosen.args.get("delta", 0) or 0),
                },
            )
        for chain_id in acting:
            chain = state.chains[chain_id]
            if chain.status == "bankrupt":
                continue
            shadow = chain.model_copy(deep=True)
            pending = next((item for item in actions if item.actor.id == f"ceo:{chain_id}"), None)
            if pending is not None and pending.kind == "set_chain_price_index":
                delta = int(pending.args.get("delta", 0))
                shadow.price_index += delta
                for store in shadow.stores:
                    store.price_index += delta
            for store in shadow.stores:
                if store.status != "open":
                    continue
                observation = _observe(
                    snap,
                    ActorRef(kind="store_manager", id=store.id),
                    {store.city},
                    {"store_id": store.id},
                )
                player_index = int(
                    observation.public.get("player_price_index", {}).get(store.city, shadow.price_index)
                )
                picked = choose_manager_action(shadow, store.id, player_index=player_index, week=snap.week)
                if picked is not None and picked.kind != "hold":
                    actions.append(picked)
        for supplier_id, _name, dept in SUPPLIERS:
            hidden = supplier_id == "labelco" and not snap.private_label
            quote = state.supplier_quotes.get(supplier_id, SupplierQuote(supplier_id=supplier_id))
            commodity = int(snap.factors.get(str(DEPT_COMMODITY[dept]), 100))
            shortage = int(snap.factors.get("66", 100)) < 100 or int(snap.factors.get("64", 100)) < 100
            actions.extend(
                supplier_actions(
                    supplier_id,
                    quote,
                    list(snap.accounts.get(supplier_id, [])),
                    commodity_index=commodity,
                    shortage=shortage,
                    slip_index=int(snap.factors.get("60", 100)),
                    week=snap.week,
                    hidden=hidden,
                )
            )
        actions.extend(
            town_actions(
                seed=snap.seed,
                week=snap.week,
                day=snap.day,
                permits=list(snap.public.get("permits") or []),
                factors=snap.factors,
                doors=_door_counts(snap),
            )
        )
        if snap.northline_smart:
            home = str(snap.northline.get("city") or "evansville")
            observation = _observe(
                snap, ActorRef(kind="northline", id="northline"), {home}, dict(snap.northline)
            )
            player_index = int(observation.public.get("player_price_index", {}).get(home, 100))
            actions.append(
                choose_northline(snap.northline, player_index=player_index, seed=snap.seed, week=snap.week)
            )
        return actions

    def shopper_card(self, snap: Snapshot, rng: object = None) -> ShopperCard:
        del rng
        player_ids = [str(row["id"]) for row in snap.public.get("player_stores") or []]
        if not _live(snap) or snap.ai is None or not snap.ai.enabled:
            return bake_card(
                week=snap.week,
                enabled=False,
                segments=self.segments,
                stores=[{"id": store_id, "owner": "player"} for store_id in player_ids],
                income_by_city={},
            )
        stores = _shopper_stores(snap)
        income = {
            city: int(snap.factors.get(factor_key(14, city), snap.factors.get("14", 100))) for city in CITIES
        }
        card = bake_card(
            week=snap.week,
            enabled=True,
            segments=self.segments,
            stores=stores,
            income_by_city=income,
        )
        for store in stores:
            city = str(store.get("city") or "")
            store_id = str(store.get("id") or "")
            if not city or store_id not in card.visit_mult:
                continue
            card.visit_mult[store_id] = int(round(card.visit_mult[store_id] * traffic_mult(snap.factors, city)))
        snap.ai.shopper_card = card
        return card

    def advise(self, snap: Snapshot, request: dict | None = None, rng: object = None) -> list[Advice]:
        del request, rng
        if not _live(snap):
            return []
        bands = {}
        if snap.ai is not None:
            for chain_id in sorted(snap.ai.chains):
                bands[chain_id] = cash_band(
                    snap.ai.chains[chain_id].cash, snap.seed, snap.week, chain_id, snap.day
                )
        stockouts = [(str(a), str(b)) for a, b in snap.hidden.get("stockouts", [])]
        northline = snap.northline or {}
        brief = AdvisorBriefing(
            day=snap.day,
            week=snap.week,
            stockouts=stockouts,
            player_weekly_net=int(snap.hidden.get("player_weekly_net", 0)),
            player_cash=int(snap.hidden.get("player_cash", 0)),
            northline_heat=int(northline.get("heat", 0)),
            northline_focus=str(northline.get("focus", "grocery")),
            northline_city=str(northline.get("city", "evansville")),
            factor_24=int(snap.factors.get("24", 100)),
            lead_time_days=_lead(snap),
            supplier_id="meadowgrove",
            supplier_name="Meadowgrove Pantry",
            permits=list(snap.public.get("permits") or []),
            bands=bands,
        )
        return compose_advice(brief)

    def on_event(self, snap: Snapshot, event: GameEvent) -> None:
        if not _live(snap) or snap.ai is None or not snap.ai.enabled:
            return
        if event.name == "PlayerBasketIndex" and event.city:
            index = int(event.payload.get("index", 100))
            for chain_id in _acting(snap):
                chain = snap.ai.chains[chain_id]
                memory = ensure_memory(snap.ai.memories, f"ceo:{chain_id}")
                previous = int(memory.ref_price.get(event.city, index))
                delta = previous - index
                if delta > 2:
                    update_belief(memory, "price_cut")
                elif delta < -2:
                    update_belief(memory, "price_up")
                else:
                    update_belief(memory, "quiet")
                if delta >= 3 and _has_open_store(chain, event.city):
                    person = snap.ai.personalities[chain.personality_id]
                    add_grudge(memory, person.grudge_gain)
                if abs(delta) > 2:
                    append_move(
                        memory,
                        {"week": event.week, "kind": "observed_price", "city": event.city, "delta": delta},
                    )
                memory.ref_price[event.city] = index
        elif event.name == "PlayerStoreOpened" and event.city:
            for chain_id in _acting(snap):
                chain = snap.ai.chains[chain_id]
                memory = ensure_memory(snap.ai.memories, f"ceo:{chain_id}")
                update_belief(memory, "opened")
                if _has_open_store(chain, event.city):
                    person = snap.ai.personalities[chain.personality_id]
                    add_grudge(memory, person.grudge_gain)


def _live(snap: Snapshot) -> bool:
    return bool(snap.ai_enabled) and snap.difficulty != "off"


def _shuffle_chains(seed: int, player_chain_id: str) -> list[str]:
    order = [chain_id for chain_id in CHAINS if chain_id != player_chain_id]
    rng = ai_rng(seed, "ai.init", 0, "chain_order", player_chain_id)
    for index in range(len(order) - 1, 0, -1):
        swap = rng.randrange(index + 1)
        order[index], order[swap] = order[swap], order[index]
    return order


def _materialize(snap: Snapshot, state: AIState) -> None:
    count = CHAIN_COUNTS[snap.difficulty]
    for index, chain_id in enumerate(state.roster):
        if index >= count:
            break
        if chain_id not in state.chains:
            state.chains[chain_id] = _build_chain(snap, state, chain_id, index)


def _build_chain(snap: Snapshot, state: AIState, chain_id: str, index: int) -> RivalChain:
    archetype = _ARCHETYPE_BY_SLOT[index % 3]
    person = next(item for item in state.personalities.values() if item.archetype == archetype)
    city = CITIES[index % len(CITIES)]
    store = RivalStore(
        id=f"store:{chain_id}:{city}:1",
        city=city,
        opened_on=snap.day,
        status="open",
        distance_band=2,
        weekly_sales=0,
        focus_dept="grocery",
        price_index=person.price_index,
    )
    return RivalChain(
        chain_id=chain_id,
        personality_id=person.id,
        price_index=person.price_index,
        cash=15_000_000,
        debt=0,
        credit_line=10_000_000,
        stores=[store],
        mandate=Mandate(growth_vs_profit=_GROWTH[archetype]),
        # Stagger the first big call so chains do not open on the same Sunday.
        cooldowns={"opening": snap.week + index * 3, "big_call": snap.week + index * 2},
    )


def _seed_prices(snap: Snapshot, state: AIState) -> None:
    prices = snap.public.get("player_price_index") or {}
    for chain_id in state.chains:
        memory = ensure_memory(state.memories, f"ceo:{chain_id}")
        for city in CITIES:
            if city in prices:
                memory.ref_price[city] = int(prices[city])


def _acting(snap: Snapshot) -> list[str]:
    assert snap.ai is not None
    count = CHAIN_COUNTS[snap.difficulty]
    chosen: list[str] = []
    for index, chain_id in enumerate(snap.ai.roster):
        if index >= count:
            break
        chain = snap.ai.chains.get(chain_id)
        if chain is None:
            continue
        chosen.append(chain_id)
    return chosen


def _board_vetoes(chain: RivalChain, action: Action) -> bool:
    """Defence in depth for a big call that already failed the cash cushion or the debt cap.

    Operating cost is opex, rent and interest. Cost of goods is not cash that has to sit in the drawer.
    A chain with under 13 weeks of history is judged on forecast earnings, which the menu already used.
    """
    from open_late.ai.legal import board_blocks

    return board_blocks(chain, action)


def _own_chain(chain: RivalChain) -> dict:
    return {
        "chain_id": chain.chain_id,
        "cash": chain.cash,
        "debt": chain.debt,
        "price_index": chain.price_index,
        "status": chain.status,
    }


def _observe(snap: Snapshot, actor: ActorRef, cities: set[str], own: dict):
    return build_observation(
        seed=snap.seed,
        week=snap.week,
        day=snap.day,
        actor=actor,
        factors=snap.factors,
        public=snap.public,
        own=own,
        cities_with_channel=cities,
    )


def _visit_mult(state: AIState, chain: RivalChain) -> int:
    card = state.shopper_card
    if card is None or not chain.stores:
        return 1000
    values = [card.visit_mult.get(store.id, 1000) for store in chain.stores]
    return int(round(sum(values) / len(values)))


def _has_open_store(chain: RivalChain, city: str) -> bool:
    return any(store.city == city and store.status == "open" for store in chain.stores)


def _war_cut(snap: Snapshot, city: str) -> int:
    until = int((snap.public.get("war_until") or {}).get(city, 0))
    if snap.week <= until:
        return int(snap.wars.get(city, 0)) // 2
    return 0


def _shelf_price(price: int, cut: int) -> int:
    if cut <= 0:
        return price
    return clamp_price(price - cut)


def _door_counts(snap: Snapshot) -> dict[str, int]:
    counts = {city: 0 for city in CITIES}
    for row in snap.public.get("player_stores") or []:
        city = str(row.get("city") or "")
        if city in counts:
            counts[city] += 1
    if snap.ai is not None:
        for chain in snap.ai.chains.values():
            if chain.status == "bankrupt":
                continue
            for store in chain.stores:
                if store.status in {"open", "building"} and store.city in counts:
                    counts[store.city] += 1
    return counts


def _market_stores(snap: Snapshot) -> list[dict]:
    """Public doors every chain can see, including permits that are not open yet."""
    return _shopper_stores(snap, include_building=True)


def _shopper_stores(snap: Snapshot, *, include_building: bool = False) -> list[dict]:
    stores: list[dict] = []
    for row in snap.public.get("player_stores") or []:
        city = str(row.get("city"))
        stores.append(
            {
                "id": str(row["id"]),
                "city": city,
                "owner": "player",
                "chain_id": "player",
                "price_index": _shelf_price(
                    int((snap.public.get("player_price_index") or {}).get(city, 100)),
                    _war_cut(snap, city),
                ),
                "distance_band": int(row.get("distance_band", 1)),
                "trust": int(row.get("trust", 60)),
                "promo": int(row.get("promo", 0)),
                "stockouts": int(row.get("stockouts", 0)),
                "focus": str(row.get("focus", "grocery")),
                "planogram": int(row.get("planogram", 50)),
                "selection": int(row.get("selection", 50)),
                "wait": int(row.get("wait", 0)),
            }
        )
    assert snap.ai is not None
    for chain_id, chain in sorted(snap.ai.chains.items()):
        if chain.status == "bankrupt":
            continue
        visible = {"open", "building"} if include_building else {"open"}
        for store in chain.stores:
            if store.status not in visible:
                continue
            stores.append(
                {
                    "id": store.id,
                    "city": store.city,
                    "owner": "rival",
                    "chain_id": chain_id,
                    "price_index": _shelf_price(store.price_index, _war_cut(snap, store.city)),
                    "distance_band": store.distance_band,
                    "trust": 50,
                    "promo": store.promo_depth,
                    "stockouts": int(store.stockouts),
                    "focus": store.focus_dept,
                    "planogram": int(store.planogram_quality),
                    "selection": 50 if int(store.planogram_quality) <= 50 else min(100, int(store.planogram_quality)),
                    "wait": {"lean": 2, "normal": 0, "heavy": -1}.get(store.staffing, 0),
                }
            )
    northline = snap.northline or {}
    if int(northline.get("heat", 0)) >= 20:
        stores.append(
            {
                "id": "northline",
                "city": str(northline.get("city", "evansville")),
                "owner": "northline",
                "chain_id": "northline",
                "price_index": int(northline.get("price_index", 102)),
                "distance_band": 2 if int(northline.get("blocks_away", 8)) <= 10 else 3,
                "trust": int(northline.get("reputation", 38)),
                "promo": 0,
                "stockouts": 0,
                "focus": str(northline.get("focus", "grocery")),
            }
        )
    stores.append(
        {
            "id": "online",
            "city": "",
            "owner": "online",
            "chain_id": "online",
            "price_index": int(snap.factors.get("86", 100)),
            "distance_band": 2,
            "trust": 50,
            "promo": 0,
            "stockouts": 0,
            "focus": "",
        }
    )
    return stores


def _lead(snap: Snapshot) -> int:
    if snap.ai is None:
        return 7
    quote = snap.ai.supplier_quotes.get("meadowgrove")
    if quote is None:
        return 7
    return quote.lead_time_days
