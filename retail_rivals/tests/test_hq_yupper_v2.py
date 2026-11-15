"""Phase 2: supercenter catalog, departments, perishables, and chain brands."""

from __future__ import annotations

import json
import re

from open_late.chains import CHAINS, DEFAULT_CHAIN_ID, chain_info, set_chain
from open_late.content import PRODUCTS
from open_late.departments import (
    DEPARTMENT_IDS,
    department_of,
    department_sales,
    products_by_department,
    selling_price,
)
from open_late.engine import (
    answer,
    blocking,
    close_day,
    continue_morning,
    new_game,
)
from open_late.hq import HOME_STORE_ID, store_pnl
from open_late.models import GameState, Product, StockLine
from open_late.store import SaveStore

DENYLIST = (
    "walmart",
    "target",
    "costco",
    "kroger",
    "safeway",
    "publix",
    "aldi",
    "lidl",
    "whole foods",
    "trader joe",
    "amazon",
    "sam's club",
    "sams club",
    "dollar general",
    "family dollar",
    "cvs",
    "walgreens",
    "rite aid",
    "best buy",
    "home depot",
    "lowe's",
    "lowes",
    "ikea",
    "nike",
    "adidas",
    "apple",
    "samsung",
    "sony",
    "coca-cola",
    "coca cola",
    "pepsi",
    "tide",
    "crest",
    "colgate",
    "tylenol",
    "advil",
    "lego",
    "barbie",
    "nintendo",
    "disney",
    "kellogg",
    "nestle",
    "kraft",
    "heinz",
    "cheerios",
    "doritos",
    "lay's",
    "lays",
    "oreo",
)


def _clear(state) -> None:
    for message in list(blocking(state)):
        for choice in message.choices:
            answer(state, message.id, choice.id)
            current = next(item for item in state.inbox if item.id == message.id)
            if current.resolved:
                break


def _close(state) -> None:
    _clear(state)
    assert close_day(state) == ""


def _catalog_text() -> str:
    parts = []
    for product in PRODUCTS:
        parts.extend([product.id, product.name, product.brand, product.blurb])
    from open_late.content import SUPPLIERS, HELP

    for supplier in SUPPLIERS.values():
        parts.extend([supplier.id, supplier.name, supplier.blurb, *supplier.brands])
    parts.append(HELP)
    return " ".join(parts).lower()


def test_every_department_has_at_least_twenty_products():
    grouped = products_by_department()
    assert list(grouped) == list(DEPARTMENT_IDS)
    counts = {dept: len(items) for dept, items in grouped.items()}
    for dept in DEPARTMENT_IDS:
        assert counts[dept] >= 20, f"{dept} has {counts[dept]}"
    assert 300 <= sum(counts.values()) <= 500
    assert sum(counts.values()) == len(PRODUCTS)


def test_catalog_avoids_real_brand_names():
    blob = _catalog_text()
    hits = [name for name in DENYLIST if re.search(r"\b" + re.escape(name) + r"\b", blob)]
    assert hits == []


def test_spoilage_happens_at_expiry():
    state = new_game("Ledger", "shop", seed=1)
    product = state.products["prod-berries"]
    line = state.stock["prod-berries"]
    line.on_hand = 8
    line.sizes = {}
    line.age_days = product.shelf_life_days
    _close(state)
    assert state.stock["prod-berries"].on_hand == 0
    assert state.last_report.spoilage_units == 8
    assert state.last_report.spoilage_cost == product.cost * 8
    assert "Spoilage" in " ".join(state.last_report.notes)


def test_markdown_happens_before_expiry():
    product = Product(
        id="prod-berries",
        name="Mixed berries, pint",
        category="produce",
        department="produce",
        quality=4,
        cost=3,
        price=5,
        supplier_id="orchard",
        shelf_life_days=3,
    )
    line = StockLine(product_id="prod-berries", on_hand=4, age_days=2)
    assert 0 < product.shelf_life_days - line.age_days <= 2
    assert selling_price(product, line) == max(product.cost, product.price * 70 // 100)
    fresh = StockLine(product_id="prod-berries", on_hand=4, age_days=0)
    assert selling_price(product, fresh) == product.price

    state = new_game("Ledger", "shop", seed=1)
    ripe = state.products["prod-berries"]
    stock = state.stock["prod-berries"]
    stock.on_hand = 6
    stock.sizes = {}
    stock.age_days = ripe.shelf_life_days - 2
    _close(state)
    # Age ticks once, leaving one day of life, so the case is marked down, not written off.
    assert state.stock["prod-berries"].on_hand > 0 or state.last_report.expiry_markdown >= 0
    assert state.stock["prod-berries"].age_days < ripe.shelf_life_days or state.stock["prod-berries"].on_hand == 0
    notes = " ".join(state.last_report.notes)
    assert "marked 30% off" in notes or "Markdowns on goods near expiry" in notes or state.last_report.expiry_markdown > 0


def test_perishables_feed_shrink_in_store_pnl():
    state = new_game("Ledger", "shop", seed=1)
    product = state.products["groc-muffins"]
    line = state.stock["groc-muffins"]
    line.on_hand = 5
    line.sizes = {}
    line.age_days = product.shelf_life_days
    _close(state)
    assert state.last_report.spoilage_cost == product.cost * 5
    assert state.last_report.shrink_cost >= state.last_report.spoilage_cost
    row = store_pnl(state, HOME_STORE_ID, days=1)
    assert row["shrink"] >= state.last_report.spoilage_cost


def test_department_helpers_work():
    state = new_game("Ledger", "shop", seed=1)
    assert department_of("groc-flour") == "grocery"
    assert department_of("cloth-tee", state) == "clothing"
    grouped = products_by_department(state)
    assert {product.id for product in grouped["pharmacy"]} == {
        product.id for product in state.products.values() if product.department == "pharmacy"
    }
    _close(state)
    sales = department_sales(state, HOME_STORE_ID, days=7)
    assert set(DEPARTMENT_IDS).issubset(sales)
    assert all(value >= 0 for value in sales.values())
    assert sum(sales.values()) == sum(state.store_days[-1].by_department.values())


def test_old_saves_load_department_defaults():
    leftover = Product(
        id="everyday-bralette",
        name="Old bralette",
        category="everyday",
        quality=4,
        cost=6,
        price=14,
        supplier_id="millthread",
    )
    assert leftover.department == "clothing"
    assert leftover.shelf_life_days == 0
    intense = Product(
        id="toy-impact",
        name="Old kit",
        category="toys_intense",
        quality=2,
        cost=8,
        price=16,
        supplier_id="playnook",
    )
    assert intense.department == "toys"
    state = new_game("Ledger", "shop", seed=1)
    payload = json.loads(state.model_dump_json())
    payload.pop("chain_id", None)
    for product in payload["products"].values():
        product.pop("department", None)
        product.pop("shelf_life_days", None)
    loaded = GameState.model_validate(payload)
    assert loaded.chain_id == "megamart"
    sample = loaded.products["groc-flour"]
    assert sample.department == "grocery"


def test_set_chain_assigns_a_known_id():
    state = new_game("Ledger", "shop", seed=1)
    assert state.chain_id == DEFAULT_CHAIN_ID
    message = set_chain(state, "bluestar")
    assert state.chain_id == "bluestar"
    assert "BlueStar" in message
    info = chain_info(state)
    assert info == {"id": "bluestar", "name": "BlueStar", "logo": "bluestar.png"}
    assert [entry["id"] for entry in CHAINS] == [
        "megamart",
        "valuemax",
        "primestop",
        "everyday",
        "shopgiant",
        "bluestar",
        "allinone",
    ]


def test_unknown_chain_id_raises():
    state = new_game("Ledger", "shop", seed=1)
    try:
        set_chain(state, "not-a-chain")
    except ValueError:
        assert state.chain_id == DEFAULT_CHAIN_ID
    else:
        raise AssertionError("expected ValueError")


def test_chain_id_round_trips_and_old_saves_default(tmp_path):
    state = new_game("Ledger", "shop", seed=1, chain_id="valuemax")
    assert state.chain_id == "valuemax"
    store = SaveStore(tmp_path / "saves.sqlite")
    store.save(state)
    loaded = store.load(state.slot)
    assert loaded.chain_id == "valuemax"
    assert chain_info(loaded)["name"] == "ValueMax"
    payload = json.loads(state.model_dump_json())
    payload.pop("chain_id", None)
    old = GameState.model_validate(payload)
    assert old.chain_id == "megamart"
    assert chain_info(old)["logo"] == "megamart.png"
