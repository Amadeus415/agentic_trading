#!/usr/bin/env python3
"""Fail-closed Codex PreToolUse guard for Robinhood order mutations."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

PROTECTED_TOOLS = {
    "place_equity_order",
    "cancel_equity_order",
    "place_option_order",
    "cancel_option_order",
}


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return _deny("Edgecraft could not parse the Codex tool event.")

    tool_name = str(event.get("tool_name", ""))
    protected = next(
        (name for name in PROTECTED_TOOLS if tool_name.lower().endswith(name)),
        None,
    )
    if protected is None:
        return 0

    if protected != "place_equity_order":
        return _deny(f"{protected} is not enabled by the autonomous equity mandate.")

    token = os.environ.get("EDGECRAFT_PERMIT_TOKEN")
    ledger_path = os.environ.get("EDGECRAFT_LEDGER_PATH")
    if not token or not ledger_path:
        return _deny("Robinhood placement requires an Edgecraft single-use permit.")

    try:
        allowed, reason = _claim_permit(
            Path(ledger_path),
            token,
            protected,
            event.get("tool_input", {}),
        )
    except Exception:
        return _deny("Edgecraft permit validation failed closed.")
    if not allowed:
        return _deny(reason)
    return _allow("Edgecraft validated and claimed the single-use placement permit.")


def _claim_permit(
    ledger_path: Path,
    token: str,
    tool_name: str,
    tool_input: Any,
) -> tuple[bool, str]:
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    connection = sqlite3.connect(ledger_path, timeout=10)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("BEGIN IMMEDIATE")
        halt = connection.execute(
            "SELECT value FROM controls WHERE name = 'trading_halted'"
        ).fetchone()
        if halt is not None and halt["value"] == "true":
            connection.rollback()
            return False, "The Edgecraft trading kill switch is active."
        permit = connection.execute(
            """
            SELECT allowed_tool, constraints, status, expires_at
            FROM permits WHERE token_hash = ?
            """,
            (token_hash,),
        ).fetchone()
        if permit is None:
            connection.rollback()
            return False, "The Edgecraft placement permit is unknown."
        if permit["status"] != "issued":
            connection.rollback()
            return False, "The Edgecraft placement permit has already been used or revoked."
        if permit["allowed_tool"] != tool_name:
            connection.rollback()
            return False, "The Edgecraft permit does not authorize this broker tool."
        expires_at = datetime.fromisoformat(permit["expires_at"])
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if datetime.now(UTC) >= expires_at.astimezone(UTC):
            connection.execute(
                "UPDATE permits SET status = 'expired' WHERE token_hash = ?",
                (token_hash,),
            )
            connection.commit()
            return False, "The Edgecraft placement permit has expired."
        constraints = json.loads(permit["constraints"])
        mismatch = _constraint_mismatch(constraints, tool_input)
        if mismatch:
            connection.rollback()
            return False, mismatch
        connection.execute(
            """
            UPDATE permits
            SET status = 'claimed', claimed_at = ?
            WHERE token_hash = ? AND status = 'issued'
            """,
            (datetime.now(UTC).isoformat(), token_hash),
        )
        connection.commit()
        return True, ""
    finally:
        connection.close()


def _constraint_mismatch(constraints: dict[str, Any], tool_input: Any) -> str | None:
    leaves = _flatten(tool_input)
    aliases = {
        "account_id_hash": {"account_id", "accountid"},
        "symbol": {"symbol", "ticker"},
        "side": {"side"},
        "dollar_notional": {"dollar_notional", "notional", "amount"},
        "order_type": {"order_type", "ordertype"},
        "time_in_force": {"time_in_force", "timeinforce"},
    }
    for expected_key, names in aliases.items():
        if expected_key not in constraints:
            continue
        observed = [value for key, value in leaves if key in names]
        if not observed:
            return f"Robinhood tool input is missing permitted {expected_key}."
        matches = (
            any(_account_reference(str(value)) == constraints[expected_key] for value in observed)
            if expected_key == "account_id_hash"
            else any(_equivalent(constraints[expected_key], value) for value in observed)
        )
        if observed and not matches:
            return f"Robinhood tool input does not match permitted {expected_key}."
    return None


def _flatten(value: Any) -> list[tuple[str, Any]]:
    if isinstance(value, dict):
        result: list[tuple[str, Any]] = []
        for key, item in value.items():
            normalized = str(key).lower().replace("-", "_")
            if isinstance(item, (dict, list)):
                result.extend(_flatten(item))
            else:
                result.append((normalized, item))
        return result
    if isinstance(value, list):
        result = []
        for item in value:
            result.extend(_flatten(item))
        return result
    return []


def _equivalent(expected: Any, actual: Any) -> bool:
    try:
        return abs(Decimal(str(expected)) - Decimal(str(actual))) <= Decimal("0.01")
    except (InvalidOperation, ValueError):
        return str(expected).strip().lower() == str(actual).strip().lower()


def _account_reference(account_id: str) -> str:
    return (
        "acct_"
        + hashlib.sha256(f"edgecraft-account-reference:{account_id}".encode()).hexdigest()[:20]
    )


def _deny(reason: str) -> int:
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                }
            }
        )
    )
    return 0


def _allow(context: str) -> int:
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "allow",
                    "additionalContext": context,
                }
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
