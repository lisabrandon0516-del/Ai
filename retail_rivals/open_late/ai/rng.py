"""Seeded AI random streams.

The spec forbids drawing from the engine RNG. Each call builds a new
``random.Random`` from blake2b of the seed, stream, week, and keys, so call
order does not matter and ``PYTHONHASHSEED`` cannot change the result.
"""

from __future__ import annotations

import hashlib
import random

from open_late.ai.constants import RESERVED_STREAMS


def ai_rng(seed: int, stream: str, week: int, *keys: object) -> random.Random:
    if stream not in RESERVED_STREAMS:
        raise ValueError(f"unknown ai stream {stream!r}")
    material = f"rr-ai-v1|{seed}|{stream}|{week}|{keys}"
    digest = hashlib.blake2b(material.encode("utf-8"), digest_size=8).digest()
    return random.Random(int.from_bytes(digest, "big"))
