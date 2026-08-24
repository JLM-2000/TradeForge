"""Small SQLite development adapter with append-only ledger guarantees."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping

from .domain import (
    ControlRecord,
    ControlState,
    ExecutionMode,
    LedgerEvent,
    Origin,
    utc_now,
    new_id,
)


def _json_default(value: Any) -> str:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if hasattr(value, "value"):
        return str(value.value)
    raise TypeError(f"cannot serialize {type(value).__name__}")


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


class SQLiteStore:
    """Persistence boundary used by M1 and replaceable by PostgreSQL later."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        self.connection = sqlite3.connect(self.path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA busy_timeout = 5000")
        if self.path != ":memory:":
            self.connection.execute("PRAGMA journal_mode = WAL")
        self.initialize()

    def initialize(self) -> None:
        schema_path = Path(__file__).resolve().parents[2] / "migrations" / "001_initial.sql"
        schema = schema_path.read_text(encoding="utf-8")
        with self.connection:
            self.connection.executescript(schema)
            self.connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                ("001_initial", _timestamp(utc_now())),
            )

    def close(self) -> None:
        self.connection.close()

    def append_event(
        self,
        event_type: str,
        account_id: str,
        mode: ExecutionMode,
        origin: Origin,
        payload: Mapping[str, Any],
        occurred_at: datetime | None = None,
        event_id: str | None = None,
    ) -> LedgerEvent:
        occurred_at = (occurred_at or utc_now()).astimezone(UTC)
        event_id = event_id or new_id("evt")
        payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=_json_default)
        with self.connection:
            previous_row = self.connection.execute(
                "SELECT event_hash FROM ledger_events ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
            previous_hash = previous_row["event_hash"] if previous_row else ""
            material = "|".join((previous_hash, event_id, event_type, _timestamp(occurred_at), account_id, mode.value, origin.value, payload_json))
            event_hash = hashlib.sha256(material.encode("utf-8")).hexdigest()
            event = LedgerEvent(
                event_id=event_id,
                event_type=event_type,
                occurred_at=occurred_at,
                account_id=account_id,
                mode=mode,
                origin=origin,
                payload=payload,
                previous_hash=previous_hash,
                event_hash=event_hash,
            )
            self.connection.execute(
                """INSERT INTO ledger_events
                (event_id, event_type, occurred_at, account_id, mode, origin,
                 payload_json, previous_hash, event_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    event.event_id,
                    event.event_type,
                    _timestamp(event.occurred_at),
                    event.account_id,
                    event.mode.value,
                    event.origin.value,
                    payload_json,
                    event.previous_hash,
                    event.event_hash,
                ),
            )
        return event

    def events(self) -> tuple[LedgerEvent, ...]:
        rows = self.connection.execute("SELECT * FROM ledger_events ORDER BY rowid ASC").fetchall()
        return tuple(
            LedgerEvent(
                event_id=row["event_id"],
                event_type=row["event_type"],
                occurred_at=datetime.fromisoformat(row["occurred_at"]),
                account_id=row["account_id"],
                mode=ExecutionMode(row["mode"]),
                origin=Origin(row["origin"]),
                payload=json.loads(row["payload_json"]),
                previous_hash=row["previous_hash"],
                event_hash=row["event_hash"],
            )
            for row in rows
        )

    def verify_ledger(self) -> tuple[bool, str]:
        previous_hash = ""
        for event in self.events():
            payload_json = json.dumps(event.payload, sort_keys=True, separators=(",", ":"), default=_json_default)
            material = "|".join((previous_hash, event.event_id, event.event_type, _timestamp(event.occurred_at), event.account_id, event.mode.value, event.origin.value, payload_json))
            expected = hashlib.sha256(material.encode("utf-8")).hexdigest()
            if event.previous_hash != previous_hash or event.event_hash != expected:
                return False, event.event_id
            previous_hash = event.event_hash
        return True, ""

    def load_control(self) -> ControlRecord:
        row = self.connection.execute("SELECT * FROM control_state WHERE singleton_id = 1").fetchone()
        if row is None:
            raise RuntimeError("control state is missing")
        activated_at = datetime.fromisoformat(row["activated_at"]) if row["activated_at"] else None
        return ControlRecord(
            state=ControlState(row["state"]),
            reason=row["reason"],
            activated_at=activated_at,
            cancel_pending_on_pause=bool(row["cancel_pending_on_pause"]),
        )

    def save_control(self, record: ControlRecord) -> None:
        with self.connection:
            self.connection.execute(
                """UPDATE control_state
                SET state = ?, reason = ?, activated_at = ?, cancel_pending_on_pause = ?
                WHERE singleton_id = 1""",
                (
                    record.state.value,
                    record.reason,
                    _timestamp(record.activated_at) if record.activated_at else None,
                    int(record.cancel_pending_on_pause),
                ),
            )

    def remember_idempotency_key(self, key: str, intent_id: str, account_id: str, instrument_id: str, payload: Mapping[str, Any]) -> None:
        with self.connection:
            self.connection.execute(
                """INSERT INTO trade_intents
                (intent_id, idempotency_key, account_id, instrument_id, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (intent_id, key, account_id, instrument_id, json.dumps(payload, default=_json_default, sort_keys=True), _timestamp(utc_now())),
            )

    def has_idempotency_key(self, key: str) -> bool:
        row = self.connection.execute("SELECT 1 FROM trade_intents WHERE idempotency_key = ?", (key,)).fetchone()
        return row is not None
