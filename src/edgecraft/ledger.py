from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from edgecraft.autonomy_models import Mandate
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
                    mandate_id TEXT,
                    run_id TEXT,
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
                CREATE TABLE IF NOT EXISTS mandates (
                    mandate_id TEXT PRIMARY KEY,
                    enabled INTEGER NOT NULL,
                    mode TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    mandate_id TEXT NOT NULL REFERENCES mandates(mandate_id),
                    cycle_key TEXT NOT NULL,
                    status TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    detail TEXT NOT NULL DEFAULT '',
                    payload TEXT NOT NULL DEFAULT '{}',
                    UNIQUE(mandate_id, cycle_key)
                );
                CREATE INDEX IF NOT EXISTS runs_status ON runs(status);
                CREATE TABLE IF NOT EXISTS runtime_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL REFERENCES runs(run_id),
                    event_type TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS runtime_events_run_id ON runtime_events(run_id, id);
                CREATE TABLE IF NOT EXISTS permits (
                    token_hash TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES runs(run_id),
                    proposal_id TEXT NOT NULL REFERENCES proposals(proposal_id),
                    order_key TEXT NOT NULL,
                    allowed_tool TEXT NOT NULL,
                    constraints TEXT NOT NULL,
                    status TEXT NOT NULL,
                    issued_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    claimed_at TEXT
                );
                CREATE TABLE IF NOT EXISTS controls (
                    name TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    reason TEXT NOT NULL
                );
                """
            )
            self._ensure_column(connection, "proposals", "mandate_id", "TEXT")
            self._ensure_column(connection, "proposals", "run_id", "TEXT")

    @staticmethod
    def _ensure_column(
        connection: sqlite3.Connection,
        table: str,
        column: str,
        definition: str,
    ) -> None:
        columns = {
            row["name"] for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if column not in columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def upsert_mandate(self, mandate: Mandate, *, now: datetime | None = None) -> None:
        timestamp = now or datetime.now(UTC)
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO mandates (mandate_id, enabled, mode, updated_at, payload)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(mandate_id) DO UPDATE SET
                    enabled = excluded.enabled,
                    mode = excluded.mode,
                    updated_at = excluded.updated_at,
                    payload = excluded.payload
                """,
                (
                    mandate.mandate_id,
                    int(mandate.enabled),
                    mandate.mode,
                    timestamp.isoformat(),
                    mandate.model_dump_json(),
                ),
            )

    def get_mandate(self, mandate_id: str) -> Mandate:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT payload FROM mandates WHERE mandate_id = ?", (mandate_id,)
            ).fetchone()
        if row is None:
            raise ValueError(f"unknown mandate_id: {mandate_id}")
        return Mandate.model_validate_json(row["payload"])

    def list_mandates(self) -> list[Mandate]:
        with self._connection() as connection:
            rows = connection.execute("SELECT payload FROM mandates ORDER BY mandate_id").fetchall()
        return [Mandate.model_validate_json(row["payload"]) for row in rows]

    def start_run(
        self,
        mandate: Mandate,
        cycle_key: str,
        *,
        now: datetime | None = None,
    ) -> str:
        self.upsert_mandate(mandate, now=now)
        timestamp = now or datetime.now(UTC)
        identity = f"{mandate.mandate_id}:{cycle_key}"
        run_id = "run_" + hashlib.sha256(identity.encode()).hexdigest()[:24]
        try:
            with self._connection() as connection:
                connection.execute(
                    """
                    INSERT INTO runs (
                        run_id, mandate_id, cycle_key, status, mode,
                        started_at, updated_at, detail, payload
                    ) VALUES (?, ?, ?, 'started', ?, ?, ?, '', '{}')
                    """,
                    (
                        run_id,
                        mandate.mandate_id,
                        cycle_key,
                        mandate.mode,
                        timestamp.isoformat(),
                        timestamp.isoformat(),
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise DuplicateProposalError(
                f"cycle {cycle_key} for mandate {mandate.mandate_id} already has a run"
            ) from exc
        self.record_runtime_event(run_id, "run_started", {"cycle_key": cycle_key}, now=timestamp)
        return run_id

    def update_run(
        self,
        run_id: str,
        status: str,
        *,
        detail: str = "",
        payload: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> None:
        timestamp = now or datetime.now(UTC)
        with self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE runs
                SET status = ?, detail = ?, payload = ?, updated_at = ?
                WHERE run_id = ?
                """,
                (
                    status,
                    detail,
                    json.dumps(payload or {}, sort_keys=True),
                    timestamp.isoformat(),
                    run_id,
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError(f"unknown run_id: {run_id}")
        self.record_runtime_event(
            run_id,
            f"run_{status}",
            {"detail": detail, **(payload or {})},
            now=timestamp,
        )

    def get_run(self, run_id: str) -> dict[str, Any]:
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            raise ValueError(f"unknown run_id: {run_id}")
        result = dict(row)
        result["payload"] = json.loads(result["payload"])
        return result

    def get_run_for_cycle(
        self,
        mandate_id: str,
        cycle_key: str,
    ) -> dict[str, Any] | None:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT * FROM runs
                WHERE mandate_id = ? AND cycle_key = ?
                """,
                (mandate_id, cycle_key),
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["payload"] = json.loads(result["payload"])
        return result

    def list_runs(self, *, limit: int = 50) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM runs ORDER BY started_at DESC LIMIT ?", (limit,)
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["payload"] = json.loads(item["payload"])
            result.append(item)
        return result

    def record_runtime_event(
        self,
        run_id: str,
        event_type: str,
        payload: dict[str, Any],
        *,
        now: datetime | None = None,
    ) -> None:
        timestamp = now or datetime.now(UTC)
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO runtime_events (run_id, event_type, occurred_at, payload)
                VALUES (?, ?, ?, ?)
                """,
                (
                    run_id,
                    event_type,
                    timestamp.isoformat(),
                    json.dumps(payload, sort_keys=True),
                ),
            )

    def issue_permit(
        self,
        run_id: str,
        proposal_id: str,
        order_key: str,
        *,
        allowed_tool: str = "place_equity_order",
        constraints: dict[str, Any] | None = None,
        ttl_seconds: int = 300,
        now: datetime | None = None,
    ) -> str:
        if ttl_seconds < 1 or ttl_seconds > 900:
            raise ValueError("permit ttl_seconds must be between 1 and 900")
        if self.trading_halted():
            raise RuntimeError("trading kill switch is active")
        timestamp = now or datetime.now(UTC)
        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        with self._connection() as connection:
            proposal = connection.execute(
                """
                SELECT mode, approved_for_review, payload
                FROM proposals WHERE proposal_id = ?
                """,
                (proposal_id,),
            ).fetchone()
            if proposal is None:
                raise ValueError(f"unknown proposal_id: {proposal_id}")
            if proposal["mode"] != "live" or not proposal["approved_for_review"]:
                raise ValueError("permits require an approved live proposal")
            payload = json.loads(proposal["payload"])
            order_keys = {order["order_key"] for order in payload.get("orders", [])}
            if order_key not in order_keys:
                raise ValueError("permit order_key is not part of the proposal")
            connection.execute(
                """
                INSERT INTO permits (
                    token_hash, run_id, proposal_id, order_key, allowed_tool,
                    constraints, status, issued_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'issued', ?, ?)
                """,
                (
                    token_hash,
                    run_id,
                    proposal_id,
                    order_key,
                    allowed_tool,
                    json.dumps(constraints or {}, sort_keys=True),
                    timestamp.isoformat(),
                    (timestamp + timedelta(seconds=ttl_seconds)).isoformat(),
                ),
            )
        self.record_runtime_event(
            run_id,
            "permit_issued",
            {
                "proposal_id": proposal_id,
                "order_key": order_key,
                "allowed_tool": allowed_tool,
                "expires_at": (timestamp + timedelta(seconds=ttl_seconds)).isoformat(),
            },
            now=timestamp,
        )
        return token

    def cycle_placed_notional(self, mandate_id: str, cycle_key: str) -> float:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT e.payload
                FROM events e
                JOIN proposals p ON p.proposal_id = e.proposal_id
                JOIN runs r ON r.run_id = p.run_id
                WHERE p.mandate_id = ? AND r.cycle_key = ? AND e.event_type = 'placed'
                """,
                (mandate_id, cycle_key),
            ).fetchall()
        return sum(float(json.loads(row["payload"]).get("notional", 0)) for row in rows)

    def set_trading_halt(
        self,
        halted: bool,
        *,
        reason: str,
        now: datetime | None = None,
    ) -> None:
        timestamp = now or datetime.now(UTC)
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO controls (name, value, updated_at, reason)
                VALUES ('trading_halted', ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at,
                    reason = excluded.reason
                """,
                ("true" if halted else "false", timestamp.isoformat(), reason),
            )
            if halted:
                connection.execute(
                    """
                    UPDATE permits SET status = 'revoked'
                    WHERE status = 'issued'
                    """
                )

    def trading_halted(self) -> bool:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT value FROM controls WHERE name = 'trading_halted'"
            ).fetchone()
        return bool(row and row["value"] == "true")

    def add_proposal(self, proposal: TradeProposal) -> None:
        payload = proposal.model_dump_json()
        try:
            with self._connection() as connection:
                connection.execute(
                    """
                    INSERT INTO proposals (
                        proposal_id, mandate_id, run_id, created_at, account_id, mode,
                        approved_for_review, payload
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        proposal.proposal_id,
                        proposal.mandate_id,
                        proposal.run_id,
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
            mandates = connection.execute("SELECT COUNT(*) AS count FROM mandates").fetchone()
            runs = connection.execute("SELECT COUNT(*) AS count FROM runs").fetchone()
            last_event = connection.execute(
                "SELECT event_type, occurred_at FROM events ORDER BY id DESC LIMIT 1"
            ).fetchone()
        return {
            "path": str(self.path.resolve()),
            "proposals": proposals["count"],
            "events": events["count"],
            "mandates": mandates["count"],
            "runs": runs["count"],
            "trading_halted": self.trading_halted(),
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
