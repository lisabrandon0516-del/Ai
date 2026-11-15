"""Player-facing reason strings.

Templates only. No model writes prose. Every string stays within 160
characters and uses fictional names.
"""

from __future__ import annotations

from open_late.ai.constants import BANNED_WORDS, REASON_MAX, chain_name, city_name


def reason(text: str) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) > REASON_MAX:
        cleaned = cleaned[: REASON_MAX - 3].rstrip() + "..."
    lowered = cleaned.lower()
    for banned in BANNED_WORDS:
        if banned in lowered:
            raise ValueError(f"reason uses a banned name: {banned}")
    return cleaned


def ceo_reason(chain_id: str, kind: str, args: dict) -> str:
    name = chain_name(chain_id)
    city = city_name(str(args.get("city", ""))) if args.get("city") else ""
    if kind == "set_chain_price_index":
        delta = int(args.get("delta", 0))
        direction = "cut" if delta < 0 else "raised"
        return reason(f"{name} {direction} its basket by {abs(delta)} points.")
    if kind == "open_store":
        return reason(f"{name} filed to open a store in {city}.")
    if kind == "close_store":
        return reason(f"{name} will close its {city} door.")
    if kind == "remodel":
        return reason(f"{name} will remodel its {city} door.")
    if kind == "start_price_war":
        return reason(f"{name} started a price war in {city}.")
    if kind == "end_price_war":
        return reason(f"{name} ended the price war in {city}.")
    if kind == "promo":
        dept = str(args.get("dept", "grocery")).replace("_", " ")
        return reason(
            f"{name} is promoting {dept} in {city} at {int(args.get('depth', 0))}% off."
        )
    if kind == "copy_best_seller":
        return reason(f"{name} shifted its {city} focus to the busiest department.")
    if kind == "cut_costs":
        return reason(f"{name} cut store costs by {int(args.get('pct', 0))}%.")
    if kind == "defend":
        return reason(f"{name} matched a public price in {city}.")
    if kind == "raise_capital":
        return reason(f"{name} raised capital against its credit line.")
    if kind == "pay_down_debt":
        return reason(f"{name} paid down debt.")
    if kind == "do_nothing":
        return reason(f"{name} held its plan this week.")
    return reason(f"{name} took a {kind.replace('_', ' ')} step.")


def board_reason(chain_id: str, kind: str) -> str:
    name = chain_name(chain_id)
    if kind == "set_mandate":
        return reason(f"The {name} board reset the chain's mandate.")
    if kind == "replace_ceo":
        return reason(f"The {name} board replaced its chief executive.")
    if kind == "declare_distress":
        return reason(f"{name} is distressed after four weeks below zero cash.")
    if kind == "file_bankruptcy":
        return reason(f"{name} filed for bankruptcy and is locked out.")
    if kind == "reenter":
        return reason(f"{name} came back after the lockout as a new entrant.")
    if kind == "approve_or_veto":
        return reason(f"The {name} board voted on a pending big call.")
    return reason(f"The {name} board met.")


def manager_reason(chain_id: str, city: str, kind: str) -> str:
    name = chain_name(chain_id)
    place = city_name(city)
    if kind == "set_local_price":
        return reason(f"The {name} manager in {place} moved the local ticket.")
    if kind == "set_focus":
        return reason(f"The {name} manager in {place} changed the local focus.")
    if kind == "set_staffing":
        return reason(f"The {name} manager in {place} reset staffing.")
    if kind == "request_promo":
        return reason(f"The {name} manager in {place} asked the chain for a promo.")
    if kind == "markdown":
        return reason(f"The {name} manager in {place} marked down aged stock.")
    return reason(f"The {name} manager in {place} held the local plan.")


def supplier_reason(supplier_name: str, kind: str) -> str:
    if kind == "adjust_cost":
        return reason(f"{supplier_name} adjusted list cost with its commodity index.")
    if kind == "allocate":
        return reason(f"{supplier_name} split scarce stock by relationship and volume.")
    if kind == "quote_lead_time":
        return reason(f"{supplier_name} quoted this week's lead time.")
    if kind == "offer_terms":
        return reason(f"{supplier_name} set terms from relationship and volume.")
    return reason(f"{supplier_name} held its quote.")


def town_reason(city: str, kind: str, weeks: int | None = None) -> str:
    place = city_name(city) if city else "the region"
    if kind == "permit":
        span = weeks if weeks is not None else 0
        return reason(f"{place} delayed the store permit by {span} weeks.")
    if kind == "schedule_road_work":
        return reason(f"{place} scheduled road work from the public traffic index.")
    if kind == "propose_wage_floor":
        return reason(f"{place} proposed a wage-floor move.")
    if kind == "set_fair_schedule":
        return reason(f"{place} adjusted fair-schedule tightness.")
    if kind == "set_bag_rule":
        return reason(f"{place} adjusted the bag rule.")
    if kind == "schedule_inspection":
        return reason(f"{place} set the inspection schedule.")
    if kind == "sales_tax_drift":
        return reason(f"{place} posted a sales-tax drift.")
    return reason(f"{place} left local rules unchanged.")


def northline_reason(kind: str) -> str:
    if kind == "set_price_index":
        return reason("Northline Market stepped its local price.")
    if kind == "set_focus":
        return reason("Northline Market changed its focus department.")
    if kind == "set_blocks":
        return reason("Northline Market moved closer, no nearer than three blocks.")
    if kind == "invest_reputation":
        return reason("Northline Market spent on its local reputation.")
    return reason("Northline Market held its shop as it is.")


def check_public_copy(text: str) -> None:
    """Raise if copy uses a banned outside-world brand."""
    lowered = text.lower()
    for banned in BANNED_WORDS:
        if banned in lowered:
            raise ValueError(banned)
