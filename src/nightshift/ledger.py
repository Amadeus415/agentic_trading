"""One append-only, hash-chained event log per run.

Every fact about an account is an event: `open` (starting cash), `fill`,
`settle`, `forecast`, `resolve` (a forecast market's outcome), and `mark`
(positions valued at the bid). Cash and positions are a fold over the events,
so the log is the whole truth. SQLite triggers refuse updates and deletes, and
each event's hash covers the previous one, so any edit breaks `verify`.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    seq INTEGER PRIMARY KEY,
    at TEXT NOT NULL,
    kind TEXT NOT NULL,
    data TEXT NOT NULL,
    prev TEXT NOT NULL,
    hash TEXT NOT NULL UNIQUE
);
CREATE TRIGGER IF NOT EXISTS no_update BEFORE UPDATE ON events
BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;
CREATE TRIGGER IF NOT EXISTS no_delete BEFORE DELETE ON events
BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;
"""
GENESIS = "0" * 64


def now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _hash(prev: str, seq: int, at: str, kind: str, data: str) -> str:
    return hashlib.sha256(f"{prev}|{seq}|{at}|{kind}|{data}".encode()).hexdigest()


def _json(data: dict[str, Any]) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)


@dataclass
class Position:
    market: str
    outcome: str
    shares: Decimal = Decimal("0")
    cost: Decimal = Decimal("0")  # dollars paid for the shares still held, fees included
    event: str = ""
    question: str = ""


@dataclass
class Account:
    cash: Decimal = Decimal("0")
    positions: dict[tuple[str, str], Position] = field(default_factory=dict)
    fees: Decimal = Decimal("0")
    marks: dict[tuple[str, str], Decimal] = field(default_factory=dict)
    marked_at: str | None = None

    def value(self, marks: dict[tuple[str, str], Decimal] | None = None) -> Decimal:
        marks = self.marks if marks is None else marks
        held = sum(
            (p.shares * marks.get(key, Decimal("0")) for key, p in self.positions.items()),
            Decimal("0"),
        )
        return self.cash + held


class Ledger:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.db = sqlite3.connect(
            self.path, timeout=30, isolation_level=None, check_same_thread=False
        )
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)

    def close(self) -> None:
        self.db.close()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Serialize writers across processes: the session server and the ticker."""
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
        self.db.execute("COMMIT")

    def append(self, kind: str, data: dict[str, Any], at: str | None = None) -> dict[str, Any]:
        if not self.db.in_transaction:
            with self.transaction():
                return self.append(kind, data, at)
        at = at or now_iso()
        body = _json(data)
        row = self.db.execute("SELECT seq, hash FROM events ORDER BY seq DESC LIMIT 1").fetchone()
        seq, prev = (row[0] + 1, row[1]) if row else (1, GENESIS)
        digest = _hash(prev, seq, at, kind, body)
        self.db.execute(
            "INSERT INTO events (seq, at, kind, data, prev, hash) VALUES (?, ?, ?, ?, ?, ?)",
            (seq, at, kind, body, prev, digest),
        )
        return {"seq": seq, "at": at, "kind": kind, **data}

    def events(self, kind: str | None = None) -> list[dict[str, Any]]:
        sql, args = "SELECT seq, at, kind, data FROM events", ()
        if kind:
            sql, args = sql + " WHERE kind = ?", (kind,)
        rows = self.db.execute(sql + " ORDER BY seq", args).fetchall()
        return [{"seq": s, "at": a, "kind": k, **json.loads(d)} for s, a, k, d in rows]

    def verify(self) -> int:
        """Check the hash chain end to end; return the number of events."""
        prev, count = GENESIS, 0
        for seq, at, kind, data, row_prev, digest in self.db.execute(
            "SELECT seq, at, kind, data, prev, hash FROM events ORDER BY seq"
        ):
            count += 1
            if seq != count or row_prev != prev or _hash(prev, seq, at, kind, data) != digest:
                raise ValueError(f"{self.path}: hash chain broken at event {seq}")
            prev = digest
        return count

    def account(self) -> Account:
        return fold(self.events())


def fold(events: list[dict[str, Any]]) -> Account:
    acct = Account()
    for e in events:
        kind = e["kind"]
        if kind == "open":
            acct.cash = Decimal(e["cash"])
        elif kind == "fill":
            key = (e["market"], e["outcome"])
            pos = acct.positions.setdefault(
                key, Position(e["market"], e["outcome"], event=e.get("event", ""))
            )
            pos.question = e.get("question", pos.question)
            shares, cash = Decimal(e["shares"]), Decimal(e["cash"])
            acct.cash += cash
            acct.fees += Decimal(e["fee"])
            if e["side"] == "buy":
                pos.shares += shares
                pos.cost -= cash
            else:
                pos.cost -= pos.cost * shares / pos.shares
                pos.shares -= shares
            if pos.shares == 0:
                del acct.positions[key]
        elif kind == "settle":
            acct.cash += Decimal(e["cash"])
            acct.positions.pop((e["market"], e["outcome"]), None)
        elif kind == "mark":
            acct.marks = {(m["market"], m["outcome"]): Decimal(m["price"]) for m in e["positions"]}
            acct.marked_at = e["at"]
    return acct
