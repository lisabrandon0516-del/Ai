"""The player's advisor.

It sees the player's own screen and public rival bands. It does not see a
rival's exact cash, and it never returns an action that places an order or
signs a deal. Numbers are ranges.
"""

from __future__ import annotations

from dataclasses import dataclass

from open_late.ai.constants import chain_name, city_name
from open_late.ai.models import ActorRef, Advice, MoneyRange, Recommendation
from open_late.ai.reasons import reason


@dataclass
class AdvisorBriefing:
    day: int
    week: int
    stockouts: list[tuple[str, str]]
    player_weekly_net: int
    player_cash: int
    northline_heat: int
    northline_focus: str
    northline_city: str
    factor_24: int
    lead_time_days: int
    supplier_id: str
    supplier_name: str
    permits: list[dict]
    bands: dict[str, MoneyRange]


def _range_weeks(point: int) -> str:
    low = max(0, point - 3)
    high = point + 3
    return f"{low}–{high} weeks"


def compose_advice(brief: AdvisorBriefing) -> list[Advice]:
    notes: list[Advice] = []
    if brief.factor_24 >= 110 and brief.lead_time_days >= 7:
        notes.append(
            _advice(
                brief,
                "hold-truck",
                f"Hold the {brief.supplier_name} truck one day.",
                (
                    f"Harvest Card is on the calendar and the quoted lead time is "
                    f"{max(0, brief.lead_time_days - 2)}–{brief.lead_time_days + 2} days."
                ),
                Recommendation(
                    action_id="hold-truck",
                    label=f"Open {brief.supplier_name}",
                    app_id="inventory",
                    supplier_id=brief.supplier_id,
                    department="grocery",
                ),
                confidence=65,
                band="likely",
            )
        )
    if brief.stockouts:
        store_id, dept = brief.stockouts[0]
        label = dept.replace("_", " ")
        notes.append(
            _advice(
                brief,
                "stockout",
                f"Cover the {label} gap.",
                f"The {store_id} door is showing a {label} stockout on your screen.",
                Recommendation(
                    action_id="cover-stockout",
                    label="Open inventory",
                    app_id="inventory",
                    store_id=store_id,
                    department=dept,
                ),
                confidence=70,
                band="likely",
            )
        )
    if brief.player_weekly_net < 0 and brief.player_cash > 0:
        burn = abs(brief.player_weekly_net)
        runway = brief.player_cash // burn
        notes.append(
            _advice(
                brief,
                "runway",
                "Cash runway is getting short.",
                f"At the current weekly loss, the drawer lasts about {_range_weeks(runway)}.",
                Recommendation(
                    action_id="review-cash",
                    label="Open the economy desk",
                    app_id="economy",
                ),
                confidence=75,
                band="likely",
            )
        )
    if brief.northline_heat >= 20:
        place = city_name(brief.northline_city) if brief.northline_city else "town"
        focus = brief.northline_focus.replace("_", " ")
        notes.append(
            _advice(
                brief,
                "northline",
                f"Northline is on {focus} at {place}.",
                "Heat is on the tape. Exact rival cash is Unknown.",
                Recommendation(
                    action_id="see-northline",
                    label="Open Market",
                    app_id="market",
                    actor=ActorRef(kind="northline", id="northline"),
                ),
                confidence=70,
                band="likely",
            )
        )
    for permit in brief.permits:
        if str(permit.get("result", "")) == "delay":
            place = city_name(str(permit.get("city", "")))
            notes.append(
                _advice(
                    brief,
                    f"permit-{permit.get('city', '')}",
                    f"A permit in {place} is public.",
                    f"{place} posted a delay of {int(permit.get('weeks', 0))} weeks.",
                    Recommendation(
                        action_id="see-permit",
                        label="Open Market",
                        app_id="market",
                    ),
                    confidence=70,
                    band="likely",
                )
            )
            break
    # Bands are ranges. Refuse to print an exact rival dollar even if handed one.
    for chain_id, band in sorted(brief.bands.items()):
        if band.low is None or band.high is None:
            continue
        # Only surface a band when the rest of the brief is empty, and never the midpoint.
        if notes:
            break
        notes.append(
            _advice(
                brief,
                f"band-{chain_id}",
                f"{chain_name(chain_id)} cash is a band, not a figure.",
                "The desk shows a range. The exact dollar is Unknown.",
                Recommendation(
                    action_id=f"see-{chain_id}",
                    label="Open Market",
                    app_id="market",
                    actor=ActorRef(kind="ceo", id=f"ceo:{chain_id}"),
                ),
                confidence=55,
                band="likely",
            )
        )
        break
    return notes[:3]


def _advice(
    brief: AdvisorBriefing,
    suffix: str,
    headline: str,
    body: str,
    recommendation: Recommendation,
    *,
    confidence: int | None,
    band: str,
) -> Advice:
    return Advice(
        id=f"advice:{brief.week}:{suffix}",
        day=brief.day,
        week=brief.week,
        headline=reason(headline),
        body=reason(body),
        recommendation=recommendation,
        confidence=confidence,
        band=band,
        unread=True,
    )
