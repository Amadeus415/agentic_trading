"""Tie fund performance to the code that produced it.

Every new cycle records ``source_revision`` (the git commit that applied it).
Older cycles predate that field, so they are attributed to the revision that
was deployed when they ran (``history/deployments.json``), labelled inferred.
Consecutive cycles on the same revision form one segment of the lineage.
"""

from __future__ import annotations

import json
import subprocess  # nosec B404 - fixed git argv, no shell
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
SHORT = 12


def _git(repo: Path, *args: str) -> str | None:
    try:
        completed = subprocess.run(  # nosec B603 B607 - fixed git argv
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return completed.stdout.strip()


def current_source_revision(repo: Path = REPO_ROOT) -> str | None:
    """Exact checked-out commit, including uncommitted and untracked changes.

    Do not cache: a long-running monitor can observe edits between cycles.
    """
    head = _git(repo.resolve(), "rev-parse", "HEAD")
    if not head:
        return None
    dirty = _git(repo.resolve(), "status", "--porcelain")
    return f"{head}+dirty" if dirty else head


@dataclass(frozen=True)
class Deployment:
    revision: str
    deployed_at: datetime
    basis: str


def load_deployments(path: Path) -> list[Deployment]:
    if not path.exists():
        return []
    rows = json.loads(path.read_text(encoding="utf-8"))["deployments"]
    deployments = [
        Deployment(
            revision=str(row["revision"])[:SHORT],
            deployed_at=datetime.fromisoformat(str(row["deployed_at"]).replace("Z", "+00:00")),
            basis=str(row["basis"]),
        )
        for row in rows
    ]
    return sorted(deployments, key=lambda item: item.deployed_at)


def commit_subjects(revisions: set[str], repo: Path = REPO_ROOT) -> dict[str, str]:
    subjects: dict[str, str] = {}
    for revision in revisions:
        clean = revision.split("+", 1)[0]
        if clean == "unknown":
            continue
        subject = _git(repo, "show", "-s", "--format=%ad %s", "--date=short", clean)
        if subject:
            subjects[revision] = subject
    return subjects


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _attribute(cycle: dict[str, Any], deployments: list[Deployment]) -> tuple[str, str]:
    runtime = (cycle.get("audit") or {}).get("runtime") or {}
    recorded = runtime.get("source_revision")
    if recorded:
        return str(recorded), "recorded"
    created = _parse(str(cycle["created_at"]))
    deployed = [item for item in deployments if item.deployed_at <= created]
    if not deployed:
        return "unknown", "no deployment record"
    return deployed[-1].revision, f"inferred from {deployed[-1].basis}"


def lineage_report(
    *,
    fund_id: str,
    initial_cash: Decimal,
    cycles: list[dict[str, Any]],
    deployments: list[Deployment],
    subjects: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Group a fund's cycles into consecutive per-revision performance segments."""
    segments: list[dict[str, Any]] = []
    nav = initial_cash
    for cycle in cycles:
        revision, basis = _attribute(cycle, deployments)
        state = cycle["state"]
        moves = list(cycle.get("fills") or []) + list(cycle.get("settlements") or [])
        if not segments or segments[-1]["revision"] != revision:
            segments.append(
                {
                    "revision": revision,
                    "basis": basis,
                    "first_cycle": cycle["cycle_key"],
                    "started_at": state["as_of"],
                    "start_nav": nav,
                    "cycles": 0,
                    "trade_cycles": 0,
                    "fills": 0,
                    "fees": Decimal("0"),
                    "realized_pnl": Decimal("0"),
                }
            )
        segment = segments[-1]
        segment["cycles"] += 1
        segment["trade_cycles"] += cycle["action"] == "trade"
        segment["fills"] += len(cycle.get("fills") or [])
        segment["fees"] += sum((Decimal(str(m.get("fee", "0"))) for m in moves), Decimal("0"))
        segment["realized_pnl"] += sum(
            (Decimal(str(m.get("realized_pnl", "0"))) for m in moves), Decimal("0")
        )
        segment["last_cycle"] = cycle["cycle_key"]
        segment["ended_at"] = state["as_of"]
        nav = Decimal(str(state["nav"]))
        segment["end_nav"] = nav

    subjects = subjects or {}
    rendered = []
    for segment in segments:
        change = segment["end_nav"] - segment["start_nav"]
        rendered.append(
            {
                **{k: v for k, v in segment.items() if not isinstance(v, Decimal)},
                "commit": subjects.get(segment["revision"], ""),
                "start_nav": str(segment["start_nav"].quantize(Decimal("0.01"))),
                "end_nav": str(segment["end_nav"].quantize(Decimal("0.01"))),
                "nav_change": str(change.quantize(Decimal("0.01"))),
                "nav_return": (
                    str((change / segment["start_nav"]).quantize(Decimal("0.0001")))
                    if segment["start_nav"]
                    else None
                ),
                "fees": str(segment["fees"].quantize(Decimal("0.01"))),
                "realized_pnl": str(segment["realized_pnl"].quantize(Decimal("0.01"))),
            }
        )
    return {
        "schema_version": "edgecraft.lineage.v1",
        "fund_id": fund_id,
        "segments": rendered,
        "interpretation": (
            "NAV change in a segment includes marks on positions opened under earlier "
            "revisions, and most segments hold few trades. Read this as a timeline of "
            "which code was live, not as causal proof that a change helped or hurt."
        ),
    }
