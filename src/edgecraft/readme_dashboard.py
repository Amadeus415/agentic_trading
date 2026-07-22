from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from edgecraft.ledger import AuditLedger
from edgecraft.observability import autonomy_health

START_MARKER = "<!-- edgecraft-console:start -->"
END_MARKER = "<!-- edgecraft-console:end -->"


def build_console_markdown(
    health: dict[str, Any],
    runs: list[dict[str, Any]],
    mandate_modes: list[str],
    *,
    generated_at: datetime,
) -> str:
    """Render a public snapshot containing aggregate operational evidence only."""
    snapshot = health["snapshot"]
    latest = runs[0] if runs else None
    status = str(health["status"])
    status_label = {
        "ready": "READY",
        "degraded": "DEGRADED",
        "halted": "HALTED",
    }.get(status, status.upper())
    latest_status = str(latest["status"]).upper() if latest else "NO RUNS YET"
    latest_time = _display_time(latest.get("updated_at") if latest else None)
    last_success = _display_time(health.get("last_success_at"))
    modes = " + ".join(sorted(set(mandate_modes))) if mandate_modes else "not configured"
    run_count = sum(int(value) for value in snapshot["runs_by_status"].values())
    approved = int(snapshot["proposals_by_approval"].get("approved", 0))
    rejected = int(snapshot["proposals_by_approval"].get("rejected", 0))
    placed = int(snapshot["order_events_by_type"].get("placed", 0))
    filled = int(snapshot["order_events_by_type"].get("filled", 0))
    unresolved = int(snapshot["unresolved_order_count"])
    halted = bool(snapshot["trading_halted"])
    generated_day = generated_at.astimezone(UTC).date().isoformat()
    warning_count = len(health.get("reasons") or [])

    return "\n".join(
        [
            START_MARKER,
            "### Daily operations snapshot",
            "",
            f"> **{status_label}** · aggregate ledger snapshot for **{generated_day} UTC**<br>",
            f"> Control-plane warnings: **{warning_count}**. Details remain in the private ledger.",
            "",
            "| Control | Current reading |",
            "|:--|:--|",
            f"| Mandate mode | `{modes}` |",
            f"| Latest cycle | `{latest_status}` · {latest_time} |",
            f"| Last successful cycle | {last_success} |",
            f"| Kill switch | `{'ACTIVE' if halted else 'INACTIVE'}` |",
            f"| Unresolved broker orders | `{unresolved}` |",
            "",
            "| Audited lifecycle | Count | What it means |",
            "|:--|--:|:--|",
            f"| Autonomous cycles | **{run_count}** | Idempotent runs persisted |",
            f"| Approved proposals | **{approved}** | Passed deterministic review gates |",
            f"| Held / rejected proposals | **{rejected}** | Cash preserved or policy blocked action |",
            f"| Orders placed | **{placed}** | Broker placement events recorded |",
            f"| Fills recorded | **{filled}** | Filled lifecycle events recorded |",
            "",
            "<sub>Generated from privacy-safe aggregate ledger fields. Account identifiers, symbols, "
            "positions, order sizes, broker payloads, credentials, and model prompts are never written "
            "here. A test, proposal, or permit is not counted as a fill.</sub>",
            END_MARKER,
        ]
    )


def update_readme(readme: Path, console: str) -> bool:
    text = readme.read_text()
    if text.count(START_MARKER) != 1 or text.count(END_MARKER) != 1:
        raise ValueError("README must contain exactly one Edgecraft console marker pair")
    start = text.index(START_MARKER)
    end = text.index(END_MARKER, start) + len(END_MARKER)
    updated = f"{text[:start]}{console}{text[end:]}"
    if updated == text:
        return False
    readme.write_text(updated)
    return True


def render_from_ledger(ledger_path: Path, *, generated_at: datetime) -> str:
    ledger = AuditLedger(ledger_path)
    health = autonomy_health(ledger)
    runs = ledger.list_runs(limit=500)
    mandate_modes = [mandate.mode for mandate in ledger.list_mandates() if mandate.enabled]
    return build_console_markdown(
        health,
        runs,
        mandate_modes,
        generated_at=generated_at,
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Refresh the aggregate, privacy-safe Edgecraft README console."
    )
    parser.add_argument("--readme", type=Path, default=Path("README.md"))
    parser.add_argument("--ledger", type=Path, default=Path("state/edgecraft.db"))
    args = parser.parse_args(argv)
    console = render_from_ledger(args.ledger, generated_at=datetime.now(UTC))
    changed = update_readme(args.readme, console)
    print("README console updated" if changed else "README console already current")


def _display_time(value: Any) -> str:
    if not value:
        return "not recorded"
    observed = datetime.fromisoformat(str(value))
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=UTC)
    return observed.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")


if __name__ == "__main__":
    main()
