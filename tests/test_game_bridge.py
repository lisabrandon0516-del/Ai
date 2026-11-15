"""The minds read the game's costs and factor card, and the holes the stand-in left open."""

from __future__ import annotations

import time
from pathlib import Path

from open_late.ai.actors.ceo import choose_ceo_action
from open_late.ai.actors.others import board_actions, town_actions
from open_late.ai.costs import city_opening_cost, traffic_mult, weekly_rent
from open_late.ai.forecast import project_action
from open_late.ai.constants import PLAYER_TYPES
from open_late.ai.memory import belief_means
from open_late.ai.models import (
    Action,
    ActorMemory,
    ActorRef,
    ChainPnL,
    GameEvent,
    RivalChain,
    RivalStore,
)
from open_late.ai.personalities import load_personalities
from open_late.ai.shoppers import load_segments
from open_late.corporate import MARKETS
from open_late.standin.sim import apply_actions, make_snapshot, simulate


def test_opening_cost_uses_the_market_and_factor_95():
    from open_late.store_costs import SUPERCENTER_BUILD_COST

    base = city_opening_cost("seattle", {"95:seattle": 100})
    assert base == SUPERCENTER_BUILD_COST["seattle"]
    assert base == MARKETS["seattle"].opening_cost
    hot = city_opening_cost("seattle", {"95:seattle": 140})
    assert hot == int(round(base * 1.4))
    houston = city_opening_cost("houston", {"95:houston": 100})
    assert houston == SUPERCENTER_BUILD_COST["houston"]
    assert MARKETS["houston"].opening_cost < MARKETS["seattle"].opening_cost
    cool = city_opening_cost("houston", {"95:houston": 90})
    assert cool == int(round(houston * 0.9))
    assert city_opening_cost("evansville", {"95:evansville": 100}) == SUPERCENTER_BUILD_COST["evansville"]
    assert MARKETS["evansville"].opening_cost == 0


def test_player_and_rival_pay_the_same():
    from open_late.store_costs import SUPERCENTER_BUILD_COST

    for city, cost in SUPERCENTER_BUILD_COST.items():
        rival = city_opening_cost(city, {f"95:{city}": 100})
        assert rival == cost
        if city == "evansville":
            assert MARKETS[city].opening_cost == 0
            continue
        assert MARKETS[city].opening_cost == rival


def test_no_hardcoded_opening_cost():
    import ast

    root = Path(__file__).resolve().parents[1] / "retail_rivals" / "open_late" / "ai"
    banned = {"WEEKLY_RENT", "SUPER_CENTER_DEAREST"}
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id in banned:
                raise AssertionError(f"{path} still names {node.id}")
            target = None
            value = None
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                target = node.targets[0].id
                value = node.value
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                target = node.target.id
                value = node.value
            if target and value is not None and any(part in target.lower() for part in ("cost", "rent", "opening")):
                if isinstance(value, ast.Constant) and isinstance(value.value, int) and value.value > 1_000_000:
                    raise AssertionError(f"{path} hardcodes {target} = {value.value}")


def test_rival_rent_matches_market_table():
    calm = weekly_rent("houston", {"88:houston": 100, "89:houston": 100})
    assert calm == MARKETS["houston"].rent_weekly
    hot = weekly_rent("las_vegas", {"88:las_vegas": 120, "89:las_vegas": 100})
    assert hot == int(round(MARKETS["las_vegas"].rent_weekly * 1.06))


def test_rent_reads_factor_88():
    calm = weekly_rent("seattle", {"88:seattle": 100, "89:seattle": 100})
    assert calm == MARKETS["seattle"].rent_weekly
    hot = weekly_rent("seattle", {"88:seattle": 130, "89:seattle": 100})
    assert hot == int(round(calm * 1.06))


def test_road_work_cuts_the_forecast():
    people, _digest = load_personalities()
    person = people["price_leader_v1"]
    chain = RivalChain(
        chain_id="valuemax",
        personality_id=person.id,
        price_index=92,
        cash=20_000_000,
        stores=[
            RivalStore(
                id="store:valuemax:houston:1",
                city="houston",
                opened_on=1,
                status="open",
                price_index=92,
            )
        ],
    )
    market = [
        {
            "id": "store:valuemax:houston:1",
            "city": "houston",
            "owner": "rival",
            "chain_id": "valuemax",
            "price_index": 92,
            "distance_band": 1,
            "trust": 50,
            "promo": 0,
            "stockouts": 0,
        },
        {
            "id": "evansville",
            "city": "houston",
            "owner": "player",
            "chain_id": "player",
            "price_index": 100,
            "distance_band": 1,
            "trust": 60,
            "promo": 0,
            "stockouts": 0,
        },
    ]
    segments = load_segments()
    quiet = project_action(
        chain,
        gross_margin_bps=person.gross_margin_bps,
        opex_bps=person.opex_bps,
        market=market,
        segments=segments,
        factors={"17:houston": 0},
    )
    torn = project_action(
        chain,
        gross_margin_bps=person.gross_margin_bps,
        opex_bps=person.opex_bps,
        market=market,
        segments=segments,
        factors={"17:houston": 1},
    )
    assert traffic_mult({"17:houston": 1}, "houston") < traffic_mult({"17:houston": 0}, "houston")
    assert torn.sales < quiet.sales


def test_a_broke_chain_cannot_open_on_credit():
    snap, _provider = make_snapshot(1, difficulty="calm")
    assert snap.ai is not None
    chain = next(iter(snap.ai.chains.values()))
    cost = city_opening_cost("seattle", snap.factors)
    chain.cash = cost - 1
    chain.debt = chain.credit_line
    action = Action(
        actor=ActorRef(kind="ceo", id=f"ceo:{chain.chain_id}"),
        kind="open_store",
        args={"city": "seattle", "site_band": 2, "cost": cost},
        reason="ValueMax filed to open a store in Seattle.",
    )
    result = apply_actions(snap, [action])[0]
    assert result.accepted is False
    assert chain.debt == chain.credit_line
    people, _digest = load_personalities()
    person = people[chain.personality_id]
    chain.cooldowns = {}
    chosen = choose_ceo_action(
        chain,
        person,
        ActorMemory(actor_id=f"ceo:{chain.chain_id}"),
        seed=1,
        week=1,
        difficulty="calm",
        opening_cost=cost,
        wars={},
        player_price={"seattle": 100},
        opening_costs={"seattle": cost, "houston": cost, "las_vegas": cost, "naperville": cost},
    )
    assert chosen.kind != "open_store"


def test_revolver_and_build_loan_are_separate():
    from open_late.ai.models import BuildLoan

    snap, _provider = make_snapshot(1, difficulty="calm")
    assert snap.ai is not None
    chain = next(iter(snap.ai.chains.values()))
    chain.cash = 20_000_000
    chain.revolver_debt = 0
    chain.refresh_debt()
    loan = 7_000_000
    action = Action(
        actor=ActorRef(kind="ceo", id=f"ceo:{chain.chain_id}"),
        kind="open_store",
        args={"city": "houston", "site_band": 2, "cost": 10_000_000, "loan": loan, "equity": 3_000_000},
        reason="ValueMax filed to open a store in Houston.",
    )
    result = apply_actions(snap, [action])[0]
    assert result.accepted is True
    assert chain.revolver_debt == 0
    assert chain.build_loans[0].principal == loan
    assert chain.debt == loan
    draw = Action(
        actor=ActorRef(kind="ceo", id=f"ceo:{chain.chain_id}"),
        kind="raise_capital",
        args={"amount": 1_000_000},
        reason="ValueMax drew the shop line.",
    )
    apply_actions(snap, [draw])
    assert chain.revolver_debt == 1_000_000
    assert chain.build_loans[0].principal == loan
    assert isinstance(chain.build_loans[0], BuildLoan)


def test_build_loan_requires_equity_and_coverage():
    from open_late.ai.legal import build_loan_terms

    people, _digest = load_personalities()
    person = people["expander_v1"]
    chain = RivalChain(
        chain_id="freshway",
        personality_id=person.id,
        price_index=98,
        cash=4_000_000,
        credit_line=10_000_000,
        ebitda_trail=[100_000],
        stores=[],
    )
    # Four million cannot fund a 30% equity stake and still leave four weeks of cost.
    allowed, loan = build_loan_terms(chain, 20_000_000, weekly_cost=400_000, incremental=80_000, ebitda_52=5_200_000)
    assert allowed is False
    assert loan == 0
    chain.cash = 12_000_000
    chain.ebitda_trail = [200_000]
    allowed, loan = build_loan_terms(chain, 20_000_000, weekly_cost=400_000, incremental=80_000, ebitda_52=10_400_000)
    assert allowed is True
    assert loan == int(20_000_000 * 0.70)
    thin, _loan = build_loan_terms(chain, 20_000_000, weekly_cost=400_000, incremental=1_000, ebitda_52=10_400_000)
    assert thin is False


def test_last_store_closes_only_when_it_cannot_earn():
    from open_late.ai.legal import last_store_cannot_earn

    people, _digest = load_personalities()
    person = people["premium_v1"]
    chain = RivalChain(
        chain_id="bluestar",
        personality_id=person.id,
        price_index=109,
        cash=1_000_000,
        ebitda_trail=[-50_000] * 8,
        stores=[
            RivalStore(id="store:bluestar:seattle:1", city="seattle", opened_on=1, status="open", price_index=109)
        ],
    )
    assert last_store_cannot_earn(chain, next_13w_contribution=-10_000) is True
    assert last_store_cannot_earn(chain, next_13w_contribution=10_000) is False
    earning = chain.model_copy(deep=True)
    earning.ebitda_trail = [20_000] * 8
    assert last_store_cannot_earn(earning, next_13w_contribution=-10_000) is False


def test_close_and_bankruptcy_match():
    snap, _provider = make_snapshot(1, difficulty="calm")
    assert snap.ai is not None
    chain = next(iter(snap.ai.chains.values()))
    store = chain.stores[0]
    from open_late.ai.models import ShopperCard

    chain.ebitda_trail = [-80_000] * 8
    chain.revolver_debt = 500_000
    chain.refresh_debt()
    snap.ai.shopper_card = ShopperCard(week=snap.week, visit_mult={store.id: 1})
    close = Action(
        actor=ActorRef(kind="ceo", id=f"ceo:{chain.chain_id}"),
        kind="close_store",
        args={"store_id": store.id, "city": store.city},
        reason="ValueMax will close its only door.",
    )
    result = apply_actions(snap, [close])[0]
    assert result.accepted is True
    assert chain.status == "bankrupt"
    assert store.status == "closed"
    assert chain.bankrupt_on == snap.day


def test_old_save_migrates():
    chain = RivalChain.model_validate(
        {
            "chain_id": "valuemax",
            "personality_id": "price_leader_v1",
            "price_index": 92,
            "cash": 1_000_000,
            "debt": 2_500_000,
        }
    )
    assert chain.revolver_debt == 2_500_000
    assert chain.build_loans == []
    assert chain.debt == 2_500_000


def test_negative_cash_draws_the_credit_line():
    people, _digest = load_personalities()
    person = people["premium_v1"]
    chain = RivalChain(
        chain_id="bluestar",
        personality_id=person.id,
        price_index=109,
        cash=-200_000,
        debt=0,
        credit_line=10_000_000,
        stores=[],
    )
    chosen = choose_ceo_action(
        chain,
        person,
        ActorMemory(actor_id="ceo:bluestar"),
        seed=1,
        week=3,
        difficulty="calm",
        opening_cost=800_000,
        wars={},
        player_price={},
    )
    assert chosen.kind == "raise_capital"
    assert int(chosen.args["amount"]) > 0


def test_every_acting_chain_learns_a_price_move():
    snap, provider = make_snapshot(4, difficulty="calm")
    assert snap.ai is not None
    acting = list(snap.ai.chains)
    assert len(acting) >= 2
    provider.on_event(
        snap,
        GameEvent(name="PlayerBasketIndex", day=8, week=2, city="houston", payload={"index": 90}),
    )
    for chain_id in acting:
        memory = snap.ai.memories[f"ceo:{chain_id}"]
        assert memory.ref_price.get("houston") == 90
        prior = belief_means({name: 1.0 for name in PLAYER_TYPES})
        assert belief_means(memory.belief)["price_fighter"] > prior["price_fighter"]


def test_board_fires_a_ceo_who_misses_the_margin():
    people, _digest = load_personalities()
    person = people["expander_v1"]
    chain = RivalChain(
        chain_id="shopgiant",
        personality_id=person.id,
        price_index=98,
        cash=5_000_000,
        last_pnl=ChainPnL(week=12, sales=1_000_000, net=-40_000),
    )
    memory = ActorMemory(actor_id="board:shopgiant")
    first = board_actions(chain, memory, person, seed=1, week=13, personalities=people)
    assert all(action.kind != "replace_ceo" for action in first)
    assert memory.counters["quarters_under"] == 1
    second = board_actions(chain, memory, person, seed=1, week=26, personalities=people)
    fired = [action for action in second if action.kind == "replace_ceo"]
    assert fired
    assert fired[0].args["personality_id"] != person.id


def test_town_rule_changes_a_factor_the_forecast_reads():
    snap, _provider = make_snapshot(1, difficulty="calm")
    doors = {city: 0 for city in ("evansville", "seattle", "houston", "las_vegas", "naperville")}
    doors["houston"] = 6
    actions = town_actions(
        seed=snap.seed, week=4, day=22, permits=[], factors=dict(snap.factors), doors=doors
    )
    rules = {action.args["cities"][0]: action for action in actions if action.kind != "permit"}
    assert rules["houston"].kind == "schedule_road_work"
    assert rules["naperville"].kind == "propose_wage_floor"
    assert rules["evansville"].kind != rules["houston"].kind
    before = traffic_mult(snap.factors, "houston")
    apply_actions(snap, [rules["houston"]])
    assert snap.factors["17:houston"] == 1
    assert traffic_mult(snap.factors, "houston") < before
    later = town_actions(
        seed=snap.seed, week=8, day=50, permits=[], factors=dict(snap.factors), doors=doors
    )
    cleared = [
        action
        for action in later
        if action.kind == "clear_rule" and action.args.get("cities") == ["houston"]
    ]
    assert cleared and cleared[0].args["factor_id"] == 17
    apply_actions(snap, cleared)
    assert snap.factors["17:houston"] == 0


def test_a_chain_cannot_close_its_only_store():
    snap, _provider = make_snapshot(1, difficulty="calm")
    assert snap.ai is not None
    chain = next(iter(snap.ai.chains.values()))
    store = chain.stores[0]
    action = Action(
        actor=ActorRef(kind="ceo", id=f"ceo:{chain.chain_id}"),
        kind="close_store",
        args={"store_id": store.id, "city": store.city},
        reason="ValueMax will close its only door.",
    )
    result = apply_actions(snap, [action])[0]
    assert result.accepted is False
    assert store.status == "open"


def test_a_storeless_chain_is_not_reopened():
    snap, _provider = make_snapshot(1, difficulty="calm")
    assert snap.ai is not None
    chain = next(iter(snap.ai.chains.values()))
    chain.stores[0].status = "closed"
    people, _digest = load_personalities()
    person = people[chain.personality_id]
    chosen = choose_ceo_action(
        chain,
        person,
        ActorMemory(actor_id=f"ceo:{chain.chain_id}"),
        seed=1,
        week=6,
        difficulty="calm",
        opening_cost=30_000_000,
        wars={},
        player_price={},
    )
    assert chosen.kind != "reopen_store"
    assert all(store.status != "open" or store.status == "closed" for store in chain.stores)
    assert chain.stores[0].status == "closed"


def test_a_bankrupt_chain_returns_after_the_lockout():
    snap, provider = make_snapshot(1, difficulty="calm")
    assert snap.ai is not None
    chain = next(iter(snap.ai.chains.values()))
    chain.status = "bankrupt"
    chain.bankrupt_on = 1
    chain.revolver_debt = 2_000_000
    chain.cash = -50_000
    chain.refresh_debt()
    chain.stores[0].status = "closed"
    person = snap.ai.personalities[chain.personality_id]
    memory = ActorMemory(actor_id=f"board:{chain.chain_id}", counters={"filed": 1})
    early = board_actions(chain, memory, person, seed=1, week=40, personalities=snap.ai.personalities)
    assert all(action.kind != "reenter" for action in early)
    stayed = board_actions(
        chain,
        memory,
        person,
        seed=1,
        week=53,
        personalities=snap.ai.personalities,
        factors=snap.factors,
        opening_costs={"seattle": 30_000_000, "houston": 19_640_000},
    )
    assert stayed == []
    assert chain.status == "bankrupt"
    chain.ebitda_trail = [400_000] * 8
    late = board_actions(
        chain,
        memory,
        person,
        seed=1,
        week=53,
        personalities=snap.ai.personalities,
        factors=snap.factors,
        opening_costs={"houston": 19_640_000, "seattle": 30_000_000, "las_vegas": 24_000_000, "naperville": 26_180_000, "evansville": 15_000_000},
    )
    assert any(action.kind == "reenter" for action in late)
    old_id = chain.stores[0].id
    apply_actions(snap, late)
    assert chain.status == "active"
    assert chain.stores[0].id == old_id
    assert chain.stores[0].status == "closed"
    assert any(store.status == "building" for store in chain.stores)
    assert chain.build_loans
    assert chain.revolver_debt == 0
    from open_late.ai.constants import ENTRANT_CASH

    assert chain.cash == ENTRANT_CASH - int(late[0].args["equity"])
    del provider


def test_building_lasts_the_delay_plus_build_days():
    from open_late.ai_bridge import market_table

    snap, _provider = make_snapshot(1, difficulty="calm")
    assert snap.ai is not None
    chain = next(iter(snap.ai.chains.values()))
    chain.cash = 20_000_000
    cost = 19_640_000
    loan = int(cost * 0.70)
    action = Action(
        actor=ActorRef(kind="ceo", id=f"ceo:{chain.chain_id}"),
        kind="open_store",
        args={"city": "houston", "site_band": 2, "cost": cost, "loan": loan, "equity": cost - loan},
        reason="ValueMax filed to open a store in Houston.",
    )
    apply_actions(snap, [action])
    permits = town_actions(
        seed=snap.seed,
        week=snap.week,
        day=snap.day,
        permits=list(snap.public["permits"]),
        factors=snap.factors,
    )
    permit = next(item for item in permits if item.kind == "permit")
    apply_actions(snap, [permit])
    building = next(store for store in chain.stores if store.city == "houston" and store.status == "building")
    delay = int(permit.args["weeks"])
    assert building.opened_on == snap.day + delay * 7 + market_table()["houston"].build_days


def test_city_pool_is_bounded():
    from open_late.ai.market import card_units
    from open_late.ai.shoppers import load_segments, visit_multipliers

    segments = load_segments()

    def city_sales(count: int) -> int:
        stores = [
            {
                "id": f"s{index}",
                "owner": "rival",
                "price_index": 100,
                "distance_band": 1,
                "trust": 50,
                "promo": 0,
                "stockouts": 0,
            }
            for index in range(count)
        ]
        stores.append(
            {"id": "online", "owner": "online", "price_index": 100, "distance_band": 2, "trust": 50, "promo": 0, "stockouts": 0}
        )
        mults = visit_multipliers(stores, segments)
        return sum(card_units(mults[f"s{index}"], 0) for index in range(count))

    one = city_sales(1)
    five = city_sales(5)
    assert five <= int(one * 1.25) + 1


def test_cannibalization_blocks_a_second_door():
    from open_late.ai.actors.ceo import _own_shift
    from open_late.ai.shoppers import load_segments

    chain = RivalChain(
        chain_id="freshway",
        personality_id="expander_v1",
        price_index=98,
        cash=20_000_000,
        ebitda_trail=[300_000] * 8,
        stores=[
            RivalStore(id="store:freshway:houston:1", city="houston", opened_on=1, status="open", price_index=98)
        ],
    )
    market = [
        {
            "id": "store:freshway:houston:1",
            "city": "houston",
            "owner": "rival",
            "chain_id": "freshway",
            "price_index": 98,
            "distance_band": 1,
            "trust": 50,
            "promo": 0,
            "stockouts": 0,
        },
        {"id": "online", "owner": "online", "city": "", "price_index": 100, "distance_band": 2, "trust": 50, "promo": 0, "stockouts": 0},
    ]
    stolen, fresh = _own_shift(market, chain, "houston", load_segments(), {"houston": 100})
    assert fresh > 0
    assert stolen / fresh > 0.40


def test_entrant_constants():
    from open_late.ai.constants import ENTRANT_CASH, ENTRANT_CREDIT_LINE

    assert ENTRANT_CASH == 15_000_000
    assert ENTRANT_CREDIT_LINE == 10_000_000


def test_no_reopen_action():
    from open_late.ai.legal import ceo_menu

    people, _digest = load_personalities()
    person = people["premium_v1"]
    chain = RivalChain(
        chain_id="bluestar",
        personality_id=person.id,
        price_index=109,
        cash=5_000_000,
        stores=[
            RivalStore(id="store:bluestar:seattle:1", city="seattle", opened_on=1, status="closed", price_index=109)
        ],
    )
    menu = ceo_menu(chain, week=6, opening_cost=30_000_000, wars={})
    assert all(action.kind != "reopen_store" for action in menu)


def test_discount_and_premium_do_not_move_alike():
    result = simulate(3, weeks=16, difficulty="calm")
    leader = result.kinds_by_archetype["price_leader"]
    premium = result.kinds_by_archetype["premium"]
    assert leader != premium


def test_a_premium_chain_does_not_race_to_the_floor():
    people, _digest = load_personalities()
    person = people["premium_v1"]
    chain = RivalChain(
        chain_id="bluestar",
        personality_id=person.id,
        price_index=90,
        cash=20_000_000,
        cooldowns={"big_call": 99, "opening": 99},
        stores=[
            RivalStore(
                id="store:bluestar:houston:1",
                city="houston",
                opened_on=1,
                status="open",
                price_index=90,
                distance_band=1,
            )
        ],
    )
    market = [
        {
            "id": "player-houston",
            "city": "houston",
            "owner": "player",
            "chain_id": "player",
            "price_index": 100,
            "distance_band": 1,
            "trust": 55,
            "promo": 0,
            "stockouts": 0,
        },
        {
            "id": "store:bluestar:houston:1",
            "city": "houston",
            "owner": "rival",
            "chain_id": "bluestar",
            "price_index": 90,
            "distance_band": 1,
            "trust": 70,
            "promo": 0,
            "stockouts": 0,
        },
    ]
    chosen = choose_ceo_action(
        chain,
        person,
        ActorMemory(actor_id="ceo:bluestar"),
        seed=1,
        week=3,
        difficulty="calm",
        opening_cost=30_000_000,
        wars={},
        player_price={"houston": 100},
        market=market,
        segments=load_segments(),
        factors={"88:houston": 100, "89:houston": 100},
    )
    assert chosen.kind == "set_chain_price_index"
    assert int(chosen.args["delta"]) > 0


def test_chains_do_not_open_on_the_same_sunday():
    snap, _provider = make_snapshot(1, difficulty="stern")
    assert snap.ai is not None
    ready = [int(chain.cooldowns.get("opening", 0)) for chain in snap.ai.chains.values()]
    assert len(set(ready)) == len(ready)
    result = simulate(5, weeks=24, difficulty="standard")
    opens = [row for row in result.actions if row.endswith(":open_store")]
    weeks = {row.split(":", 1)[0] for row in opens}
    assert len(opens) <= 6
    if len(opens) >= 2:
        assert len(weeks) >= 2


def test_rent_is_not_charged_twice():
    from open_late.ai.forecast import store_pnl

    people, _digest = load_personalities()
    person = people["premium_v1"]
    store = RivalStore(
        id="store:bluestar:seattle:1",
        city="seattle",
        opened_on=1,
        status="open",
        price_index=person.price_index,
    )
    neutral = {"88:seattle": 100, "89:seattle": 100}
    hot = {"88:seattle": 130, "89:seattle": 100}
    base = store_pnl(
        store,
        gross_margin_bps=person.gross_margin_bps,
        opex_bps=person.opex_bps,
        visit_mult=1000,
        war_intensity=0,
        cost_cut_pct=0,
        debt_share=0,
        factors=neutral,
        shelf_index=person.price_index,
    )
    stressed = store_pnl(
        store,
        gross_margin_bps=person.gross_margin_bps,
        opex_bps=person.opex_bps,
        visit_mult=1000,
        war_intensity=0,
        cost_cut_pct=0,
        debt_share=0,
        factors=hot,
        shelf_index=person.price_index,
    )
    full_rent = weekly_rent("seattle", neutral)
    # Factor 88 moves the one market lease, and it is not charged a second time.
    assert stressed.opex - base.opex == weekly_rent("seattle", hot) - full_rent
    assert stressed.opex - base.opex < full_rent // 2


def test_stern_sunday_fits_the_budget():
    snap, provider = make_snapshot(1, difficulty="stern")
    provider.weekly(snap)
    times = []
    for _ in range(4):
        started = time.perf_counter()
        provider.weekly(snap)
        times.append((time.perf_counter() - started) * 1000)
    assert sum(times) / len(times) <= 150
    assert max(times) <= 400
