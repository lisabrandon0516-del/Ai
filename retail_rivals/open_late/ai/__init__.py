"""Retail Rivals AI minds.

Actors return actions. They do not mutate the economy. Randomness comes from
``ai_rng`` only. When difficulty is ``off`` or the save has AI disabled, these
functions draw no random numbers and return no actions.
"""

from open_late.ai.provider import RetailAI
from open_late.ai.registry import ai_enabled, get_provider, register_provider
from open_late.ai.rng import ai_rng

__all__ = [
    "RetailAI",
    "ai_enabled",
    "ai_rng",
    "get_provider",
    "register_provider",
]
