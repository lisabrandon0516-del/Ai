"""Save migration for an AI block that may be missing.

Old saves load with AI disabled and no behaviour change. There is no
headquarters save in this repository; this function is the pure step.
"""

from __future__ import annotations


def migrate_ai(payload: dict) -> dict:
    data = dict(payload)
    ai = data.get("ai")
    if not isinstance(ai, dict):
        data["ai"] = {"enabled": False, "api_version": 1, "chains": {}, "log": []}
        return data
    merged = dict(ai)
    merged.setdefault("enabled", False)
    merged.setdefault("api_version", 1)
    merged.setdefault("chains", {})
    merged.setdefault("log", [])
    data["ai"] = merged
    return data
