"""SQLite saves. One row per shop, the whole state as JSON."""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from open_late.models import GameState


def default_path() -> Path:
    override = os.environ.get("OPEN_LATE_DB")
    if override:
        return Path(override)
    return Path.home() / ".open_late" / "saves.sqlite"


class SaveStore:
    def __init__(self, path: Path | None = None):
        self.path = path or default_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS saves (
                    slot TEXT PRIMARY KEY,
                    shop_name TEXT NOT NULL,
                    day INTEGER NOT NULL,
                    cash INTEGER NOT NULL,
                    updated_at TEXT NOT NULL,
                    state_json TEXT NOT NULL
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def save(self, state: GameState) -> None:
        stamp = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO saves (slot, shop_name, day, cash, updated_at, state_json)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(slot) DO UPDATE SET
                    shop_name = excluded.shop_name,
                    day = excluded.day,
                    cash = excluded.cash,
                    updated_at = excluded.updated_at,
                    state_json = excluded.state_json
                """,
                (state.slot, state.shop_name, state.day, state.cash, stamp, state.model_dump_json()),
            )

    def load(self, slot: str) -> GameState:
        with self._connect() as conn:
            row = conn.execute("SELECT state_json FROM saves WHERE slot = ?", (slot,)).fetchone()
        if row is None:
            raise KeyError(slot)
        from open_late.content import merge_catalog

        return merge_catalog(GameState.model_validate_json(row[0]))

    def list_saves(self) -> list[tuple[str, str, int, int, str]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT slot, shop_name, day, cash, updated_at FROM saves ORDER BY updated_at DESC"
            ).fetchall()
        return [(slot, name, day, cash, updated) for slot, name, day, cash, updated in rows]

    def delete(self, slot: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM saves WHERE slot = ?", (slot,))
