"""Load hash-checked personality data."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from open_late.ai.models import Personality

_DATA = Path(__file__).resolve().parent / "data" / "personalities_v1.json"


def load_personalities(path: Path | None = None) -> tuple[dict[str, Personality], str]:
    target = path or _DATA
    raw = target.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    payload = json.loads(raw)
    people = {}
    for row in payload["personalities"]:
        person = Personality.model_validate(row)
        people[person.id] = person
    return people, digest


def resolve_personalities(
    embedded: dict[str, Personality],
    shipped: dict[str, Personality],
    saved_hash: str,
    file_hash: str,
) -> tuple[dict[str, Personality], str]:
    """On a hash mismatch, keep personalities stored in the save.

    If the save has none, use the shipped file and return a warning.
    """
    if embedded:
        if saved_hash and saved_hash != file_hash:
            return embedded, "weights_hash mismatch; keeping embedded personalities"
        return embedded, ""
    if saved_hash and saved_hash != file_hash:
        return shipped, "weights_hash mismatch; no embedded personalities, using the shipped file"
    return shipped, ""
