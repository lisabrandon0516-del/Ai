"""Patch E8: expanded fictional catalog, family want, and save migration."""

from __future__ import annotations

from collections import Counter

from open_late.content import (
    LABEL_PRODUCTS,
    PRODUCTS,
    SHOP_STOCK,
    SUPPLIERS,
    family_want_units,
    iter_products,
    merge_catalog,
    want_units,
)
from open_late.departments import DEPARTMENT_IDS, department_sales
from open_late.engine import new_game
from open_late.hq import HOME_STORE_ID
from open_late.models import GameState
from pathlib import Path

from open_late.store import SaveStore
from tests.test_e6_yupper import play


def test_catalog_covers_every_department_with_hundreds_of_skus():
    assert 300 <= len(PRODUCTS) <= 500
    assert len({product.id for product in PRODUCTS}) == len(PRODUCTS)
    counts = Counter(product.department for product in PRODUCTS)
    for department in DEPARTMENT_IDS:
        assert counts[department] >= 20, (department, counts[department])
    assert all(product.price >= product.cost >= 1 for product in PRODUCTS)
    assert all(int(product.case_size) >= 1 for product in PRODUCTS)
    # Existing E7 family IDs stay in the catalog so old saves can keep their stock.
    for sku in ("groc-flour", "prod-bananas", "meat-chicken", "elec-tv", "cloth-tee"):
        assert any(product.id == sku for product in PRODUCTS)
    # Department want is unchanged; each SKU gets a family share, not the whole wall.
    assert family_want_units("grocery") < want_units("grocery")
    assert family_want_units("grocery") * counts["grocery"] >= want_units("grocery") * 10
    # Opening unit total stays at the E7a shelf pack so weekly volume stays in family.
    assert sum(SHOP_STOCK.values()) == 363_495
    # Catalog list vs runtime dict: same records, either shape works with iter_products.
    assert "meadowgrove" in SUPPLIERS and "noir" not in SUPPLIERS
    listed = [product.id for product in iter_products()]
    assert listed == [product.id for product in PRODUCTS]


def test_core_departments_sell_over_four_standard_weeks():
    state = new_game("Prairie Wire", "shop", seed=22, economy_difficulty="standard")
    result = play(state, 4)
    assert not result["failed"], result["reason"]
    whole = department_sales(state, HOME_STORE_ID, days=28)
    last = department_sales(state, HOME_STORE_ID, days=8)
    missing_whole = [dept for dept in DEPARTMENT_IDS if whole.get(dept, 0) <= 0]
    missing_last = [dept for dept in DEPARTMENT_IDS if last.get(dept, 0) <= 0]
    assert not missing_whole, (missing_whole, whole)
    assert not missing_last, (missing_last, last)


def test_old_save_gains_new_skus_without_rewriting_stock_or_prices():
    state = new_game("Prairie Wire", "shop", seed=8)
    from open_late.catalog_e8 import E8_ROWS

    e8_ids = {row[0] for row in E8_ROWS}
    legacy = [product for product in state.products.values() if product.id not in e8_ids]
    assert len(legacy) == 130
    flour_price = state.products["groc-flour"].price
    flour_stock = state.stock["groc-flour"].on_hand
    raw = state.model_dump()
    raw["save_version"] = 2
    raw["products"] = {product.id: product.model_dump() for product in legacy}
    raw["stock"] = {product.id: state.stock[product.id].model_dump() for product in legacy}
    loaded = GameState.model_validate(raw)
    assert len(loaded.products) == 130
    loaded = merge_catalog(loaded)
    assert loaded.save_version >= 3
    assert len(loaded.products) == len(PRODUCTS)
    assert loaded.products["groc-flour"].price == flour_price
    assert loaded.stock["groc-flour"].on_hand == flour_stock
    # New families arrive empty so the mid-game drawer is not gifted inventory.
    new_id = E8_ROWS[0][0]
    assert new_id in loaded.products
    assert loaded.stock[new_id].on_hand == 0
    assert "label-flour" not in loaded.products
    assert [product.id for product in iter_products(loaded)] == list(loaded.products)

    # SaveStore.load is the official path.
    store = SaveStore(Path("/tmp/e8_save_test.sqlite"))
    slim = GameState.model_validate(raw)
    slim.slot = "e8-legacy"
    store.save(slim)
    reloaded = store.load("e8-legacy")
    assert len(reloaded.products) == len(PRODUCTS)
    assert reloaded.stock["groc-flour"].on_hand == flour_stock
    store.delete("e8-legacy")
