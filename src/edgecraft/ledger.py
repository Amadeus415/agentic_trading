from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from edgecraft.execution_models import TradeProposal


class DuplicateProposalError(RuntimeError):
    pass


class AuditLedger:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS proposals (
                    proposal_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    account_id TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    approved_for_review INTEGER NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    proposal_id TEXT NOT NULL REFERENCES proposals(proposal_id),
                    event_type TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    occurred_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS events_occurred_at ON events(occurred_at);
                """
            )

    def add_proposal(self, proposal: TradeProposal) -> None:
        payload = proposal.model_dump_json()
        try:
            with self._connection() as connection:
                connection.execute(
                    """
                    INSERT INTO proposals (
                        proposal_id, created_at, account_id, mode, approved_for_review, payload
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        proposal.proposal_id,
                        proposal.created_at.isoformat(),
                        proposal.account_id,
                        proposal.mode,
                        int(proposal.risk.approved_for_review),
                        payload,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise DuplicateProposalError(
                f"proposal {proposal.proposal_id} already exists; refusing duplicate execution path"
            ) from exc

    def record_event(
        self,
        proposal_id: str,
        event_type: str,
        payload: dict[str, Any],
        *,
        idempotency_key: str | None = None,
        occurred_at: datetime | None = None,
    ) -> str:
        timestamp = occurred_at or datetime.now(UTC)
        allowed_events = {
            "reviewed",
            "placed",
            "filled",
            "partially_filled",
            "rejected",
            "canceled",
        }
        if event_type not in allowed_events:
            raise ValueError(f"unsupported event_type: {event_type}")
        if not payload.get("order_key"):
            raise ValueError("event payload must contain order_key")
        if event_type == "placed" and float(payload.get("notional", 0)) <= 0:
            raise ValueError("placed event payload must contain positive notional")
        key = idempotency_key or _event_key(proposal_id, event_type, payload)
        with self._connection() as connection:
            exists = connection.execute(
                "SELECT 1 FROM proposals WHERE proposal_id = ?", (proposal_id,)
            ).fetchone()
            if exists is None:
                raise ValueError(f"unknown proposal_id: {proposal_id}")
            try:
                connection.execute(
                    """
                    INSERT INTO events (
                        proposal_id, event_type, idempotency_key, occurred_at, payload
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        proposal_id,
                        event_type,
                        key,
                        timestamp.isoformat(),
                        json.dumps(payload, sort_keys=True),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise DuplicateProposalError(f"event idempotency key {key} already exists") from exc
        return key

    def daily_placed_notional(self, day: date | None = None) -> float:
        target = day or datetime.now(UTC).date()
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT payload FROM events
                WHERE event_type = 'placed' AND substr(occurred_at, 1, 10) = ?
                """,
                (target.isoformat(),),
            ).fetchall()
        total = 0.0
        for row in rows:
            payload = json.loads(row["payload"])
            total += float(payload.get("notional", 0.0))
        return total

    def status(self) -> dict[str, Any]:
        with self._connection() as connection:
            proposals = connection.execute("SELECT COUNT(*) AS count FROM proposals").fetchone()
            events = connection.execute("SELECT COUNT(*) AS count FROM events").fetchone()
            last_event = connection.execute(
                "SELECT event_type, occurred_at FROM events ORDER BY id DESC LIMIT 1"
            ).fetchone()
        return {
            "path": str(self.path.resolve()),
            "proposals": proposals["count"],
            "events": events["count"],
            "last_event": dict(last_event) if last_event else None,
            "unresolved_order_keys": self.unresolved_order_keys(),
        }

    def unresolved_order_keys(self) -> list[str]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT proposal_id, event_type, payload FROM events ORDER BY id"
            ).fetchall()
        unresolved: set[str] = set()
        for row in rows:
            payload = json.loads(row["payload"])
            key = str(payload.get("order_key") or row["proposal_id"])
            if row["event_type"] in {"placed", "partially_filled"}:
                unresolved.add(key)
            elif row["event_type"] in {"filled", "rejected", "canceled"}:
                unresolved.discard(key)
        return sorted(unresolved)


def _event_key(proposal_id: str, event_type: str, payload: dict[str, Any]) -> str:
    raw = json.dumps(
        {"proposal_id": proposal_id, "event_type": event_type, "payload": payload},
        sort_keys=True,
        separators=(",", ":"),
    )
    return "evt_" + hashlib.sha256(raw.encode()).hexdigest()[:24]
