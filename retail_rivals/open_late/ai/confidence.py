"""Confidence from the spec's section 3.5 formula.

The engine owns the number. This is the reference implementation of that
formula: half-life 14, corroboration +8 capped at 24, and a hard-source gate
on the Confirmed band.
"""

from __future__ import annotations

import math

from open_late.ai.constants import (
    CONFIDENCE_CORROBORATION,
    CONFIDENCE_CORROBORATION_CAP,
    HALF_LIFE_DAYS,
)
from open_late.ai.models import ConfidenceBlock, SourceRow

BASE: dict[str, int] = {
    "store_day": 85,
    "manager_memo": 75,
    "economy_news": 70,
    "supplier_statement": 65,
    "market_observe": 55,
    "rumor": 30,
    "unknown": 0,
}

KIND_ORDER: dict[str, int] = {name: index for index, name in enumerate(BASE)}

HARD_KINDS = frozenset({"store_day", "economy_news", "supplier_statement"})


def _is_hard(source: SourceRow) -> bool:
    if source.source_kind in HARD_KINDS:
        return True
    if source.source_kind == "market_observe":
        return (source.heat_at_observation or 0) >= 20
    return False


def _independent(left: SourceRow, right: SourceRow) -> bool:
    if left.source_kind != right.source_kind:
        return True
    if left.source_kind == "economy_news" and left.outlet != right.outlet:
        return True
    if left.source_kind in {"store_day", "manager_memo"} and left.door_id != right.door_id:
        return True
    if left.source_kind == "rumor" and left.source_id != right.source_id:
        return True
    return False


def score_confidence(
    sources: list[SourceRow],
    *,
    day: int,
    half_life_days: int = HALF_LIFE_DAYS,
) -> ConfidenceBlock:
    usable = [source for source in sources if source.source_kind != "unknown"]
    if not usable:
        return ConfidenceBlock(
            confidence=None,
            band="unknown",
            source_kind="unknown",
            sources=[],
            half_life_days=half_life_days,
            stale=False,
        )

    def sort_key(source: SourceRow) -> tuple[int, int, int]:
        base = BASE.get(source.source_kind, 0)
        return (-base, -source.observed_day, KIND_ORDER.get(source.source_kind, 99))

    primary = sorted(usable, key=sort_key)[0]
    age = max(0, day - primary.observed_day)
    base = BASE.get(primary.source_kind, 0)
    decayed = math.floor(base * (0.5 ** (age / half_life_days)))

    counted: list[SourceRow] = []
    for source in usable:
        if source is primary or source.source_id == primary.source_id and source.source_kind == primary.source_kind and source.observed_day == primary.observed_day and source.outlet == primary.outlet:
            continue
        source_age = max(0, day - source.observed_day)
        if source_age >= half_life_days:
            continue
        if any(not _independent(source, prior) for prior in [primary, *counted]):
            continue
        counted.append(source)

    bonus = min(CONFIDENCE_CORROBORATION_CAP, CONFIDENCE_CORROBORATION * len(counted))
    confidence = min(100, max(0, decayed + bonus))
    stale = age >= half_life_days
    hard_fresh = any(
        _is_hard(source) and max(0, day - source.observed_day) < half_life_days
        for source in usable
    )
    if confidence == 0:
        band = "unknown"
    elif confidence < 30:
        band = "rumor"
    elif confidence < 55:
        band = "unconfirmed"
    elif confidence < 80:
        band = "likely"
    elif hard_fresh:
        band = "confirmed"
    else:
        band = "likely"

    return ConfidenceBlock(
        confidence=confidence,
        band=band,
        source_kind=primary.source_kind,
        sources=usable,
        observed_day=primary.observed_day,
        half_life_days=half_life_days,
        age_days=age,
        stale=stale,
        corroboration_count=len(counted),
    )
