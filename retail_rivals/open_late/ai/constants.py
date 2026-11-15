"""Ids, fair-play tiers, and budgets from the Retail Rivals AI spec.

Section 9 recommended defaults are locked in here: this package owns the
shopper model, difficulty reuses off/calm/standard/stern, towns delay and do
not deny, and search iteration counts scale with that same difficulty field.
"""

from __future__ import annotations

CHAINS: tuple[str, ...] = (
    "megamart",
    "valuemax",
    "primestop",
    "everyday",
    "shopgiant",
    "bluestar",
    "allinone",
)

CHAIN_NAMES: dict[str, str] = {
    "megamart": "MegaMart",
    "valuemax": "ValueMax",
    "primestop": "PrimeStop",
    "everyday": "EveryDay",
    "shopgiant": "ShopGiant",
    "bluestar": "BlueStar",
    "allinone": "All-in-One",
}

CITIES: tuple[str, ...] = (
    "evansville",
    "seattle",
    "houston",
    "las_vegas",
    "naperville",
)

CITY_NAMES: dict[str, str] = {
    "evansville": "Evansville",
    "seattle": "Seattle",
    "houston": "Houston",
    "las_vegas": "Las Vegas",
    "naperville": "Naperville",
}

DEPARTMENTS: tuple[str, ...] = (
    "grocery",
    "produce",
    "meat_dairy",
    "frozen",
    "household",
    "health_beauty",
    "pharmacy",
    "electronics",
    "clothing",
    "toys",
    "home_garden",
    "sporting",
    "seasonal",
)

SEGMENTS: tuple[str, ...] = (
    "value_stretchers",
    "busy_families",
    "fresh_first",
    "brand_loyal",
    "deal_hunters",
    "online_leaners",
)

PLAYER_TYPES: tuple[str, ...] = (
    "price_fighter",
    "premium",
    "expander",
    "passive",
)

ARCHETYPES: tuple[str, ...] = (
    "price_leader",
    "premium",
    "expander",
    "custom",
)

DIFFICULTIES: tuple[str, ...] = ("off", "calm", "standard", "stern")

# How many of the six unused chains act. Off runs nothing.
CHAIN_COUNTS: dict[str, int] = {"off": 0, "calm": 2, "standard": 3, "stern": 4}

# Fixed iteration counts. Never wall-clock. Calm searches less, stern more.
# The counts stay under the Sunday budget (150 ms mean, 400 ms worst).
SEARCH_ITERS: dict[str, int] = {"off": 0, "calm": 4, "standard": 6, "stern": 8}

# Top myopic big-call candidates that receive expectimax, per chain per week.
SEARCH_SHORTLIST = 2

BIG_CALLS: frozenset[str] = frozenset(
    {"open_store", "close_store", "start_price_war", "raise_capital"}
)

# Canonical move-kind order for tie-breaks. Earlier wins.
KIND_ORDER: dict[str, int] = {
    "open_store": 0,
    "close_store": 1,
    "remodel": 2,
    "set_chain_price_index": 3,
    "start_price_war": 4,
    "end_price_war": 5,
    "promo": 6,
    "copy_best_seller": 7,
    "cut_costs": 8,
    "defend": 9,
    "raise_capital": 10,
    "pay_down_debt": 11,
    "do_nothing": 12,
}

CITY_ORDER: dict[str, int] = {city: index for index, city in enumerate(CITIES)}

OPENING_COOLDOWN_WEEKS = 8
WAR_COOLDOWN_WEEKS = 12
BIG_CALL_COOLDOWN_WEEKS = 4
PRICE_INDEX_MIN = 80
PRICE_INDEX_MAX = 130
NORTHLINE_PRICE_MIN = 86
NORTHLINE_PRICE_MAX = 120
NORTHLINE_BLOCKS_MIN = 3
LOG_WEEKS = 26
HALF_LIFE_DAYS = 14
REASON_MAX = 160
MEMORY_MOVES = 26
BANKRUPT_LOCKOUT_DAYS = 52 * 7
CASH_BAND_BUCKET = 500_000
BASE_WEEKLY_SALES = 1_800_000
WEEKLY_RENT = 25_000
CONFIDENCE_CORROBORATION = 8
CONFIDENCE_CORROBORATION_CAP = 24

# Supplier houses. labelco stays hidden until the private-label flag is on.
SUPPLIERS: tuple[tuple[str, str, str], ...] = (
    ("meadowgrove", "Meadowgrove Pantry", "grocery"),
    ("orchard", "Orchard Lane", "produce"),
    ("coldfield", "Coldfield Farms", "meat_dairy"),
    ("soapstone", "Soapstone Goods", "household"),
    ("riverwell", "Riverwell Care", "health_beauty"),
    ("sparklane", "Sparklane Tech", "electronics"),
    ("millthread", "Millthread Apparel", "clothing"),
    ("playnook", "Playnook", "toys"),
    ("yardwell", "Yardwell Supply", "home_garden"),
    ("festoon", "Festoon Seasonal", "seasonal"),
    ("labelco", "Private Label Co", "grocery"),
)

SUPPLIER_NAMES: dict[str, str] = {sid: name for sid, name, _dept in SUPPLIERS}
SUPPLIER_DEPT: dict[str, str] = {sid: dept for sid, _name, dept in SUPPLIERS}

# Commodity factor id per department (factors 67–79).
DEPT_COMMODITY: dict[str, int] = {
    dept: 67 + index for index, dept in enumerate(DEPARTMENTS)
}

RESERVED_STREAMS: frozenset[str] = frozenset(
    {
        "ai.init",
        "ai.ceo",
        "ai.board",
        "ai.store",
        "ai.north",
        "ai.supplier",
        "ai.shopper",
        "ai.town",
        "ai.advisor",
        "ai.noise",
        "ai.detect",
        "ai.search",
        "ai.tune",
    }
)

# Observability. Anything not listed is hidden (O3) so an unknown id cannot leak.
O0_FACTORS: frozenset[int] = frozenset(
    list(range(23, 37))
    + list(range(37, 46))
    + [11, 15, 16, 17, 22, 83, 84, 87, 104]
    + list(range(106, 112))
)
O1_FACTORS: frozenset[int] = frozenset(
    list(range(1, 11))
    + [12, 13, 14, 18, 19, 20, 21, 47]
    + list(range(51, 55))
    + list(range(57, 61))
    + [62]
    + list(range(64, 67))
    + list(range(67, 80))
    + [85, 86, 88, 89, 91, 95, 96, 97, 101, 103, 105]
    + list(range(112, 120))
)
O2_FACTORS: frozenset[int] = frozenset([80, 81, 82, 120])

UTILITY_TERMS: tuple[str, ...] = (
    "contribution_13w",
    "share_change",
    "cash_risk",
    "mandate_fit",
    "grudge",
    "variety",
    "regret",
)

BANNED_WORDS: tuple[str, ...] = (
    "walmart",
    "target",
    "costco",
    "kroger",
    "amazon",
    "toys r us",
    "toy's n us",
    "toys 'n' us",
    "toys'n'us",
)


def chain_name(chain_id: str) -> str:
    return CHAIN_NAMES.get(chain_id, chain_id)


def city_name(city: str) -> str:
    return CITY_NAMES.get(city, city)


def week_of(day: int) -> int:
    if day < 1:
        raise ValueError("day starts at 1")
    return (day - 1) // 7 + 1


def tier_of(factor_id: int) -> str:
    if factor_id in O0_FACTORS:
        return "O0"
    if factor_id in O1_FACTORS:
        return "O1"
    if factor_id in O2_FACTORS:
        return "O2"
    return "O3"


def factor_key(factor_id: int, scope_key: str = "") -> str:
    """Stand-in for economy._key. One place to swap when the game is wired up."""
    if scope_key:
        return f"{factor_id}:{scope_key}"
    return str(factor_id)


def parse_factor_key(key: str) -> tuple[int, str]:
    if ":" in key:
        fid, scope = key.split(":", 1)
        return int(fid), scope
    return int(key), ""
