"""Player-facing chain brands for Retail Rivals.

Logo files live in the brand pack; this module stores only the filename.
"""

from __future__ import annotations

from typing import Any

DEFAULT_CHAIN_ID = "megamart"

CHAINS: list[dict[str, str]] = [
    {"id": "megamart", "name": "MegaMart", "logo": "megamart.png"},
    {"id": "valuemax", "name": "ValueMax", "logo": "valuemax.png"},
    {"id": "primestop", "name": "PrimeStop", "logo": "primestop.png"},
    {"id": "everyday", "name": "EveryDay", "logo": "everyday.png"},
    {"id": "shopgiant", "name": "ShopGiant", "logo": "shopgiant.png"},
    {"id": "bluestar", "name": "BlueStar", "logo": "bluestar.png"},
    {"id": "allinone", "name": "All-in-One", "logo": "allinone.png"},
]

_CHAIN_BY_ID = {entry["id"]: entry for entry in CHAINS}


def chain_info(state: Any) -> dict[str, str]:
    chain_id = getattr(state, "chain_id", "") or DEFAULT_CHAIN_ID
    entry = _CHAIN_BY_ID.get(chain_id)
    if entry is None:
        return dict(_CHAIN_BY_ID[DEFAULT_CHAIN_ID])
    return dict(entry)


def set_chain(state: Any, chain_id: str) -> str:
    if chain_id not in _CHAIN_BY_ID:
        raise ValueError(f"Unknown chain id: {chain_id}")
    state.chain_id = chain_id
    name = _CHAIN_BY_ID[chain_id]["name"]
    return f"Chain set to {name}."
