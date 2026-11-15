"""Register a provider the same way a future engine hook would."""

from __future__ import annotations

from typing import Any

_PROVIDER: Any = None


def register_provider(provider: Any) -> None:
    global _PROVIDER
    _PROVIDER = provider


def get_provider() -> Any:
    return _PROVIDER


def ai_enabled(state: Any) -> bool:
    if hasattr(state, "enabled"):
        return bool(state.enabled)
    ai = getattr(state, "ai", None)
    if ai is not None and hasattr(ai, "enabled"):
        return bool(ai.enabled)
    return False
