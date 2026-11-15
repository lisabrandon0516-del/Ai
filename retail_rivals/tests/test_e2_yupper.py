"""Patch E2: weather, supply chain, news feed, and disaster cooldowns."""

from __future__ import annotations

from open_late.economy import (
    DISASTER_RANK,
    adjust_visits,
    apply_daily_spoil,
    cooldown_clear,
    economy_calendar,
    economy_daily_news,
    economy_end_day,
    economy_factor,
    economy_news,
    economy_snapshot,
    economy_tick,
    force_event,
    freight_mult,
    landed_cost,
    lead_slip_days,
    visits_mult,
    weather_label,
    _prepare_day,
    _resolve_one_disaster,
    _resolve_links,
    _bake_card,
    week_id,
)
from open_late.economy_news import OUTLETS, append_news
from open_late.engine import answer, blocking, close_day, continue_morning, new_game
from open_late.hq import HOME_STORE_ID, store_pnl


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


def test_ice_week_cuts_visits_then_catch_up():
    ice = new_game("Lakeshore Mart", "shop", seed=21, economy_difficulty="standard")
    calm = new_game("Lakeshore Mart", "shop", seed=21, economy_difficulty="standard")
    force_event(ice, 40, city_id="evansville", days=2, intensity=30, start_day=1)
    from open_late.economy import apply_player_bias

    # Ice writes 0.7 (clear 1.0) before the visible walk-bias hook; no stack cap here.
    icy = apply_player_bias(0.7, helpful=True, difficulty="standard")
    clear = apply_player_bias(1.0, helpful=True, difficulty="standard")
    assert visits_mult(ice, HOME_STORE_ID) == icy
    assert visits_mult(calm, HOME_STORE_ID) == clear
    assert weather_label(ice, "evansville") == "ice"
    ice_visits = []
    calm_visits = []
    for _ in range(2):
        _close(ice)
        _close(calm)
        ice_visits.append(ice.last_report.visits)
        calm_visits.append(calm.last_report.visits)
        continue_morning(ice)
        continue_morning(calm)
    assert ice_visits[0] < calm_visits[0]
    assert ice_visits[1] < calm_visits[1]
    # Days 3-4 are the catch-up window.
    catch_ice = []
    catch_calm = []
    for _ in range(2):
        _close(ice)
        _close(calm)
        catch_ice.append(ice.last_report.visits)
        catch_calm.append(calm.last_report.visits)
        continue_morning(ice)
        continue_morning(calm)
    assert catch_ice[0] > catch_calm[0]
    assert catch_ice[1] > catch_calm[1]
    # After the catch-up, the overlay rests.
    _prepare_day(ice)
    assert visits_mult(ice, HOME_STORE_ID) == visits_mult(calm, HOME_STORE_ID) == clear


def test_thaw_writes_shrink_into_store_pnl():
    live = new_game("Nightcourt Cases", "shop", seed=8, economy_difficulty="standard")
    off = new_game("Nightcourt Cases", "shop", seed=8)
    # Make sure frozen and dairy are on the wall.
    frozen = [p for p in live.products.values() if p.department == "frozen" and live.stock[p.id].on_hand > 0]
    dairy = [p for p in live.products.values() if p.department == "meat_dairy" and live.stock[p.id].on_hand > 0]
    assert frozen and dairy
    force_event(live, 41, city_id="evansville", days=1, severity=2, intensity=60, start_day=1)
    _close(live)
    _close(off)
    live_pnl = store_pnl(live, HOME_STORE_ID, days=1)
    off_pnl = store_pnl(off, HOME_STORE_ID, days=1)
    assert live_pnl["shrink"] > off_pnl["shrink"]
    assert live_pnl["contribution"] == (
        live_pnl["sales"]
        - live_pnl["cogs"]
        - live_pnl["labor"]
        - live_pnl["rent"]
        - live_pnl["freight"]
        - live_pnl["shrink"]
        - live_pnl["card_fees"]
        - live_pnl["pos_fees"]
    )
    notes = " ".join(live.last_report.notes).lower()
    assert "thaw" in notes
    assert "thaw" not in " ".join(off.last_report.notes).lower()
    # Thaw always earns a news slot.
    thaw_news = [item for item in economy_news(live) if 46 in item["factor_ids"]]
    assert thaw_news


def test_news_quota_and_dedupe():
    state = new_game("Harbor Desk", "shop", seed=4, economy_difficulty="standard")
    # Ten national moves in the same week; quota keeps 3.
    for fid in (1, 6, 7, 8, 10, 57, 58, 62, 65, 2):
        row = append_news(
            state,
            factor_ids=[fid],
            headline=f"Move on {fid}.",
            body="Test bulletin.",
            severity=2,
            week=0,
        )
    national = [item for item in state.economy.news if not item.get("store_ids") and not item.get("daily")]
    assert len(national) <= 3
    # A second story for the same (factor, city, week) is dropped.
    first = append_news(state, factor_ids=[44], headline="Basin one.", body="x", week=1)
    second = append_news(state, factor_ids=[44], headline="Basin two.", body="x", week=1)
    assert first is not None
    assert second is None
    # At most one local story per owned store per Sunday.
    ok = append_news(
        state,
        factor_ids=[40],
        headline="Ice one.",
        body="x",
        city_id="evansville",
        store_ids=["evansville"],
        week=2,
    )
    blocked = append_news(
        state,
        factor_ids=[39],
        headline="Rain too.",
        body="x",
        city_id="evansville",
        store_ids=["evansville"],
        week=2,
    )
    assert ok is not None
    assert blocked is None
    # Public shape and fictional outlets only.
    for item in economy_news(state, limit=10):
        assert set(item) == {
            "id",
            "day",
            "outlet",
            "headline",
            "body",
            "factor_ids",
            "store_ids",
            "severity",
            "prompt",
        }
        assert item["outlet"] in OUTLETS
    filtered = economy_news(state, store_id=HOME_STORE_ID, limit=10)
    assert isinstance(filtered, list)
    # Intra-week bulletin cap: one per store per day.
    state.day = 3
    force_event(state, 40, city_id="evansville", days=1, start_day=3)
    economy_daily_news(state)
    economy_daily_news(state)
    daily = [item for item in state.economy.news if item.get("daily") and item.get("day") == 3]
    assert len(daily) == 1


def test_cooldown_prevents_a_double_disaster():
    state = new_game("Wind Lot", "shop", seed=9, economy_difficulty="standard")
    ice = force_event(state, 40, city_id="evansville", days=2, severity=3, start_day=1)
    storm = force_event(state, 41, city_id="evansville", days=1, severity=4, start_day=1, set_cooldown=False)
    # Remove them and resolve as a same-week roll.
    state.economy.events = []
    accepted, deferred = _resolve_one_disaster(state, [ice, storm], week=0)
    assert len([item for item in accepted if item["factor_id"] in DISASTER_RANK and (item.get("city_id") == "evansville")]) == 1
    winner = next(item for item in accepted if item["factor_id"] in DISASTER_RANK)
    assert winner["factor_id"] == 41
    assert any(item["factor_id"] == 40 for item in deferred)
    # After an ice event fires, cooldown blocks the same city until it expires.
    force_event(state, 40, city_id="evansville", days=1, start_day=8)
    assert cooldown_clear(state, 40, "evansville") is False
    state.day = 8 + 7 * 4
    assert cooldown_clear(state, 40, "evansville") is True


def test_diesel_freight_passthrough_cascade_within_caps():
    state = new_game("Amberline Racks", "shop", seed=15, economy_difficulty="standard")
    # First Sunday tick bakes a lag-1 65 from a quiet previous week.
    state.day = 7
    economy_tick(state)
    first = economy_factor(state, 65)["value"]
    assert 70 <= first <= 170
    # Diesel spikes after that tick so the next week can see it (lag 1).
    state.economy.values["6"] = 160
    state.economy.values["7"] = 140
    state.day = 14
    economy_tick(state)
    passed = economy_factor(state, 65)["value"]
    assert passed > first
    assert passed == max(70, min(170, round(0.70 * 160 + 0.30 * 140))) or passed >= 130
    # Produce cogs and freight move, still inside the stacked caps.
    freight = freight_mult(state, HOME_STORE_ID)
    assert 0.75 <= freight <= 1.25
    produce = next(p for p in state.products.values() if p.department == "produce")
    billed = landed_cost(state, HOME_STORE_ID, "produce", produce.cost * 10)
    assert billed != produce.cost * 10
    assert 0.85 * produce.cost * 10 <= billed <= 1.15 * produce.cost * 10
    snap = economy_snapshot(state)
    assert isinstance(snap["events_active"], list)
    cal = economy_calendar(state, weeks=8)
    assert all(city in row["city_weather"] for row in cal for city in row["city_weather"])


def test_off_stays_an_identity_for_e2_hooks():
    off = new_game("Fair Week", "shop", seed=5)
    live = new_game("Fair Week", "shop", seed=5, economy_difficulty="standard")
    force_event(live, 40, city_id="evansville", days=2, intensity=30, start_day=1)
    force_event(off, 40, city_id="evansville", days=2, intensity=30, start_day=1)
    assert visits_mult(off, HOME_STORE_ID) == 1.0
    assert lead_slip_days(off) == 0
    assert apply_daily_spoil(off, off.stock, off.products, HOME_STORE_ID, off.last_report) == 0
    assert economy_news(off) == []
    # A Sunday off tick clears any leftover events.
    off.day = 7
    economy_tick(off)
    assert off.economy.events == []
    assert visits_mult(off, HOME_STORE_ID) == 1.0
    assert weather_label(off, "evansville") == "fair"
    # Live ice still cuts, so the hook is actually wired.
    assert visits_mult(live, HOME_STORE_ID) < 1.0
    # Adjust visits is a no-op when off even if an event was forced.
    assert adjust_visits(off, HOME_STORE_ID, 40) == 40
