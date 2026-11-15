"""Patch E5: supercenter rescale, no hidden grace, and specific news templates."""

from __future__ import annotations

import os
import re

import pytest

from open_late.content import family_want_map, family_want_units
from open_late.corporate import new_corporate, replenish
from open_late.economy import FACTORS, STATE_NEUTRAL, economy_factor, economy_factors, economy_movers, economy_news, economy_snapshot
from open_late.economy_e3 import factors_in_range
from open_late.economy_e4 import BILL_DISCOUNT, BILL_GRACE, SALES_GRACE, VISIT_BIAS
from open_late.economy_headlines import HEADLINES
from open_late.economy_news import headline_for
from open_late.engine import (
    answer,
    blocking,
    close_day,
    continue_morning,
    launch_campaign,
    new_game,
    place_capped_restock,
    set_assignment,
)
from open_late.finance import SIZE_MULT, insurance_weekly, starting_reserve, utilities_weekly
from open_late.hq import HOME_STORE_ID, store_pnl

GENERIC_FACTOR = re.compile(r"(?i)factor\s*#?\d+")
LONG_TESTS = os.environ.get("RR_LONG_TESTS") == "1"
# Default run is short; RR_LONG_TESTS=1 restores the 26-week, 5-seed sweep.
SEEDS_IN_TEST = (8, 15, 22, 31, 47) if LONG_TESTS else (22,)
SURVIVAL_WEEKS = 26 if LONG_TESTS else 8
TUNING_SEEDS = (8, 15, 22, 31, 47)

PNL_KEYS = {
    "store_id",
    "name",
    "days",
    "sales",
    "cogs",
    "labor",
    "rent",
    "freight",
    "shrink",
    "card_fees",
    "pos_fees",
    "contribution",
}


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


def _staff_care(state) -> None:
    team = [person for person in state.staff if person.employed]
    dow = (state.day - 1) % 7
    for i, person in enumerate(team):
        want = "off" if dow == (i % 7) else "floor"
        if person.assignment != want:
            set_assignment(state, person.id, want)


def _build_basket(state, departments=None) -> dict:
    basket: dict[str, dict[str, int]] = {}
    wants = family_want_map(state.products.values())
    for product in state.products.values():
        if departments is not None and product.department not in departments:
            continue
        line = state.stock.get(product.id)
        on_hand = int(line.on_hand) if line is not None else 0
        on_order = int(getattr(line, "on_order", 0) or 0) if line is not None else 0
        want = wants.get(product.department) or family_want_units(product.department, state.products.values())
        need = want - on_hand - on_order
        if need <= 0:
            continue
        basket.setdefault(product.supplier_id, {})[product.id] = need
    return basket


# E8: moderate restock cap retuned from E7c's 50k so the 26-week lift lands
# in +1.5 to +4.5 after the larger catalog. e5 kind=basic keeps the historical
# 80k sheet cap; official E6/E7/E8 basic play lives in test_e6 and uses
# REST_CAP = 30_000 * SIZE_MULT. Levers are unchanged.
MODERATE_CAP = 40_000


def _place(state, basket, reserve: int, cap_units: int = 80_000) -> int:
    if state.cash <= reserve:
        return 0
    cap = min(cap_units * SIZE_MULT, max(0, state.cash - reserve))
    return place_capped_restock(state, basket, cap, reserve, ignore_minimum=True)


def _restock(state, kind: str, reserve: int | None = None) -> None:
    if reserve is None:
        reserve = 22_000 * SIZE_MULT
    cap_units = MODERATE_CAP if kind == "moderate" else 80_000
    dow = state.day % 7
    if dow == 1:
        _place(state, _build_basket(state), reserve, cap_units=cap_units)
        return
    if dow == 4 and kind == "moderate":
        _place(state, _build_basket(state), reserve, cap_units=cap_units)
    elif dow == 4 and kind == "basic":
        _place(state, _build_basket(state, {"produce", "meat_dairy", "frozen", "grocery"}), reserve, cap_units=cap_units)


def _play(state, weeks: int, *, kind: str, promo: bool) -> dict:
    sales = 0
    contrib = 0
    cash_weeks: list[int] = []
    for _ in range(weeks * 7):
        _restock(state, kind)
        if promo and state.campaign is None and state.day % 28 == 1 and state.cash >= 8_000 * SIZE_MULT:
            launch_campaign(state, "email", "playful", "clothing", None)
        _staff_care(state)
        _close(state)
        if state.day % 7 == 0:
            pnl = store_pnl(state, HOME_STORE_ID, days=7)
            sales += int(pnl["sales"])
            contrib += int(pnl["contribution"])
            cash_weeks.append(state.cash)
        if state.failed:
            break
        continue_morning(state)
    margin = contrib / sales if sales else 0.0
    return {
        "failed": state.failed,
        "reason": state.fail_reason,
        "cash": state.cash,
        "credit": state.credit_used,
        "sales": sales,
        "contrib": contrib,
        "margin": margin,
        "cash_weeks": cash_weeks,
    }


@pytest.fixture(scope="module")
def standard_horizon():
    """One short (or long) standard play, shared by the news and range checks."""
    state = new_game("Nightcourt Dispatch", "shop", seed=22, economy_difficulty="standard")
    result = _play(state, SURVIVAL_WEEKS, kind="moderate", promo=True)
    return state, result


def test_hidden_levers_are_gone_and_starting_cash_is_visible():
    assert SALES_GRACE["calm"] == SALES_GRACE["standard"] == SALES_GRACE["stern"] == SALES_GRACE["off"] == 0.0
    assert BILL_DISCOUNT["calm"] == BILL_DISCOUNT["standard"] == BILL_DISCOUNT["stern"] == 0.0
    assert BILL_GRACE["calm"] == BILL_GRACE["standard"] == BILL_GRACE["stern"] == 0.0
    assert VISIT_BIAS["calm"] == VISIT_BIAS["standard"] == VISIT_BIAS["stern"] == 0
    assert starting_reserve("shop", "calm") > starting_reserve("shop", "standard") == starting_reserve("shop", "off")
    assert starting_reserve("shop", "stern") < starting_reserve("shop", "standard")
    off = new_game("Prairie Wire", "shop", seed=4)
    calm = new_game("Prairie Wire", "shop", seed=4, economy_difficulty="calm")
    stern = new_game("Prairie Wire", "shop", seed=4, economy_difficulty="stern")
    assert off.cash == starting_reserve("shop", "off")
    assert calm.cash == starting_reserve("shop", "calm")
    assert stern.cash == starting_reserve("shop", "stern")
    snap = economy_snapshot(calm)
    assert snap["starting_reserve"] == starting_reserve("shop", "calm")
    pnl = store_pnl(off, HOME_STORE_ID, days=1)
    assert set(pnl) >= PNL_KEYS


def test_every_factor_has_up_and_down_templates():
    assert set(HEADLINES) == set(range(1, 121)) == set(FACTORS)
    for fid in range(1, 121):
        up, down = HEADLINES[fid]
        assert isinstance(up, str) and isinstance(down, str)
        assert "{name}" in up and "{name}" in down
        assert "{size}" in up and "{size}" in down
        assert up != down


def test_headlines_never_say_factor_n(standard_horizon):
    for fid in range(1, 121):
        name = FACTORS[fid]["name"]
        for direction in ("up", "down"):
            for delta in (3, 8, 15, None):
                extra = {"factor_name": name}
                if delta is not None:
                    extra["delta"] = delta if direction == "up" else -delta
                headline, body = headline_for(
                    fid,
                    city_id="evansville",
                    department="grocery",
                    direction=direction,
                    extra=extra,
                )
                assert not GENERIC_FACTOR.search(headline), headline
                assert not GENERIC_FACTOR.search(body), body
                assert name.lower() in headline.lower()

    state, result = standard_horizon
    assert not result["failed"], result["reason"]
    feed = economy_news(state, limit=200)
    for item in feed:
        assert not GENERIC_FACTOR.search(item.get("headline") or "")
        assert not GENERIC_FACTOR.search(item.get("body") or "")




def test_every_factor_row_has_kind_neutral_band_and_label():
    state = new_game("Basin Review", "shop", seed=4, economy_difficulty="standard")
    rows = economy_factors(state, city_id="evansville")
    assert [row["id"] for row in rows] == list(range(1, 121))
    state_ids = []
    for row in rows:
        assert set(row) >= {"kind", "neutral", "band", "label"}
        assert row["kind"] in {"index", "state"}
        assert row["band"] in {"steady", "watch", "alert"}
        assert row["label"] is None or isinstance(row["label"], str)
        if row["kind"] == "index":
            assert row["neutral"] == 100
            low, high = row["range"]
            assert low <= 100 <= high
        else:
            assert row["id"] in STATE_NEUTRAL
            assert row["neutral"] == STATE_NEUTRAL[row["id"]]
            assert row["band"] == "steady"
            assert isinstance(row["label"], str) and row["label"]
            state_ids.append(row["id"])
    assert state_ids == sorted(STATE_NEUTRAL)
    # Known mis-cited examples: Northline focus is 82, house relationship is 61.
    assert FACTORS[82]["name"] == "Northline focus" and FACTORS[82]["kind"] == "state"
    assert FACTORS[61]["name"] == "House relationship residual" and FACTORS[61]["kind"] == "state"
    assert FACTORS[1]["name"] == "Policy rate" and FACTORS[1]["kind"] == "index"
    assert FACTORS[42]["name"] == "Drought" and FACTORS[42]["kind"] == "index"
    # Forced extremes still read as steady for every state factor.
    for fid in STATE_NEUTRAL:
        low, high = FACTORS[fid]["range"]
        state.economy.values[str(fid)] = high
        row = economy_factor(state, fid, city_id="evansville")
        assert row["kind"] == "state"
        assert row["band"] == "steady"
        assert row["label"]
    # Snapshot gauges and mover rankings skip state factors.
    snap = economy_snapshot(state)
    assert all(item.get("kind") == "index" for item in snap["gauges"])
    movers = economy_movers(state, city_id="evansville", limit=8)
    assert movers and all(item["kind"] == "index" for item in movers)
    assert all(item["id"] not in STATE_NEUTRAL for item in movers)


def test_index_factors_stay_near_100_and_state_bands_stay_steady(standard_horizon):
    state, result = standard_horizon
    assert not result["failed"], result["reason"]
    for fid, info in FACTORS.items():
        low, high = info["range"]
        if info["kind"] == "index":
            assert low <= 100 <= high, fid
            row = economy_factor(state, fid, city_id="evansville")
            assert low <= row["value"] <= high, (fid, row["value"], info["range"])
            if row.get("cities"):
                for value in row["cities"].values():
                    assert low <= int(value) <= high, (fid, value)
        else:
            row = economy_factor(state, fid, city_id="evansville")
            assert row["band"] == "steady", (fid, row)
            # A mid-run state value must not be scored on the 100 scale.
            assert row["kind"] == "state"


def test_calm_passive_survives_with_healthy_margins():
    margins = []
    for seed in SEEDS_IN_TEST:
        state = new_game("Harbor Ledger", "shop", seed=seed, economy_difficulty="calm")
        result = _play(state, SURVIVAL_WEEKS, kind="basic", promo=False)
        assert not result["failed"], f"seed {seed}: {result['reason']}"
        start_cash = starting_reserve("shop", "calm")
        assert result["cash"] > start_cash + 20_000 * SIZE_MULT, (seed, result["cash"], start_cash)
        assert result["credit"] == 0
        assert result["margin"] >= 0.02, (seed, result["margin"])
        assert factors_in_range(state) == []
        margins.append(result["margin"])
    assert min(margins) > 0


def test_standard_moderate_survives_with_positive_margins():
    for seed in SEEDS_IN_TEST:
        state = new_game("Harbor Ledger", "shop", seed=seed, economy_difficulty="standard")
        result = _play(state, SURVIVAL_WEEKS, kind="moderate", promo=True)
        assert not result["failed"], f"seed {seed}: {result['reason']}"
        assert result["cash"] > starting_reserve("shop", "standard")
        assert result["margin"] > 0, (seed, result["margin"])
        assert factors_in_range(state) == []


def test_stern_hurts_against_calm():
    calm_margins = []
    stern_rows = []
    for seed in SEEDS_IN_TEST:
        calm = new_game("Harbor Ledger", "shop", seed=seed, economy_difficulty="calm")
        calm_result = _play(calm, SURVIVAL_WEEKS, kind="basic", promo=False)
        calm_margins.append(calm_result["margin"])
        stern = new_game("Harbor Ledger", "shop", seed=seed, economy_difficulty="stern")
        stern_result = _play(stern, SURVIVAL_WEEKS, kind="basic", promo=False)
        stern_rows.append(stern_result)
        assert factors_in_range(stern) == []
        assert stern_result["margin"] < calm_result["margin"] - 0.005 or stern_result["failed"] or stern_result["credit"] > 0
    # At least some seeds lose money or sit near insolvency (credit drawn or failed).
    # The short default run only checks that stern is clearly worse; the long
    # sweep (seed 31 at 26 weeks) is what pins the insolvency clause.
    if LONG_TESTS:
        assert any(row["margin"] < 0 or row["failed"] or row["credit"] > 0 or row["cash"] < 15_000 * SIZE_MULT for row in stern_rows)
    assert sum(row["margin"] for row in stern_rows) / len(stern_rows) < sum(calm_margins) / len(calm_margins)


def test_corporate_chain_contribution_is_sane():
    state = new_corporate("Basin Review", seed=11, economy_difficulty="standard")
    start_cash = state.cash
    assert start_cash >= 60_000
    # Keep the first door covered. Two weeks of supply, one truck a week.
    for door in state.doors:
        door.weeks_of_supply = 2
    for _ in range(21):
        if state.day % 7 == 1:
            _place(state, _build_basket(state), reserve=25_000 * SIZE_MULT)
            for door in state.doors:
                if door.status == "open":
                    replenish(state, door.id)
        for person in state.staff:
            if person.employed and person.assignment != "floor":
                set_assignment(state, person.id, "floor")
        _staff_care(state)
        _close(state)
        if state.failed:
            break
        continue_morning(state)
    assert not state.failed, state.fail_reason
    # Sum door contribution over the last week; should be a modest share of sales, not a boutique leftover.
    sales = 0
    contrib = 0
    for door in state.doors:
        pnl = store_pnl(state, door.id, days=7)
        assert set(pnl) >= PNL_KEYS
        sales += int(pnl["sales"])
        contrib += int(pnl["contribution"])
    assert sales >= 40_000 * SIZE_MULT, sales
    share = contrib / sales if sales else 0
    assert -0.15 <= share <= 0.20, (sales, contrib, share)
    assert state.cash > 0


@pytest.mark.skipif(not LONG_TESTS, reason="set RR_LONG_TESTS=1 for the 26-week, 5-seed sweep")
def test_long_five_seed_survival():
    """Full E5 survival table: 5 seeds, 26 weeks, calm / standard / stern."""
    weeks = 26
    for seed in TUNING_SEEDS:
        calm = new_game("Harbor Ledger", "shop", seed=seed, economy_difficulty="calm")
        calm_result = _play(calm, weeks, kind="basic", promo=False)
        assert not calm_result["failed"], f"calm {seed}: {calm_result['reason']}"
        assert calm_result["cash"] > starting_reserve("shop", "calm") + 20_000 * SIZE_MULT
        assert calm_result["margin"] >= 0.02
        assert calm_result["credit"] == 0

        standard = new_game("Harbor Ledger", "shop", seed=seed, economy_difficulty="standard")
        standard_result = _play(standard, weeks, kind="moderate", promo=True)
        assert not standard_result["failed"], f"standard {seed}: {standard_result['reason']}"
        assert standard_result["cash"] > starting_reserve("shop", "standard")
        assert standard_result["margin"] > 0

        stern = new_game("Harbor Ledger", "shop", seed=seed, economy_difficulty="stern")
        stern_result = _play(stern, weeks, kind="basic", promo=False)
        assert stern_result["margin"] < calm_result["margin"] - 0.005 or stern_result["failed"] or stern_result["credit"] > 0
    # Pin the insolvency clause on the known hard seed.
    stern31 = new_game("Harbor Ledger", "shop", seed=31, economy_difficulty="stern")
    row = _play(stern31, weeks, kind="basic", promo=False)
    assert row["margin"] < 0 or row["failed"] or row["credit"] > 0 or row["cash"] < 15_000 * SIZE_MULT
