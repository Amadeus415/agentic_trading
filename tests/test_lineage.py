from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from edgecraft.lineage import Deployment, current_source_revision, lineage_report


def _cycle(key: str, created: str, nav: str, *, revision: str | None = None, fills=()):
    runtime = {"source_revision": revision} if revision else {}
    return {
        "cycle_key": key,
        "created_at": created,
        "action": "trade" if fills else "hold",
        "state": {"as_of": created, "nav": nav},
        "fills": list(fills),
        "settlements": [],
        "audit": {"runtime": runtime},
    }


def test_lineage_infers_old_cycles_and_prefers_recorded_revisions():
    deployments = [
        Deployment("aaaaaaaaaaaa", datetime(2026, 9, 1, tzinfo=UTC), "runtime reflog"),
        Deployment("bbbbbbbbbbbb", datetime(2026, 9, 10, tzinfo=UTC), "runtime reflog"),
    ]
    cycles = [
        _cycle("c1", "2026-09-02T00:00:00Z", "1010", fills=[{"fee": "1", "realized_pnl": "0"}]),
        _cycle("c2", "2026-09-05T00:00:00Z", "990"),
        _cycle("c3", "2026-09-11T00:00:00Z", "1000"),
        _cycle("c4", "2026-09-12T00:00:00Z", "1050", revision="cccccccccccc"),
    ]

    report = lineage_report(
        fund_id="f",
        initial_cash=Decimal("1000"),
        cycles=cycles,
        deployments=deployments,
    )

    segments = report["segments"]
    assert [s["revision"] for s in segments] == ["aaaaaaaaaaaa", "bbbbbbbbbbbb", "cccccccccccc"]
    assert segments[0]["cycles"] == 2 and segments[0]["trade_cycles"] == 1
    assert segments[0]["nav_change"] == "-10.00" and segments[0]["fees"] == "1.00"
    assert segments[1]["start_nav"] == "990.00" and segments[1]["nav_change"] == "10.00"
    assert segments[2]["basis"] == "recorded" and segments[2]["nav_return"] == "0.0500"
    assert segments[0]["basis"].startswith("inferred")


def test_cycles_before_any_deployment_are_unknown_not_guessed():
    report = lineage_report(
        fund_id="f",
        initial_cash=Decimal("1000"),
        cycles=[_cycle("c1", "2026-01-01T00:00:00Z", "1000")],
        deployments=[],
    )
    assert report["segments"][0]["revision"] == "unknown"


def test_source_revision_outside_git_is_none(tmp_path: Path):
    assert current_source_revision(tmp_path) is None


def test_source_revision_inside_this_checkout_is_a_commit():
    revision = current_source_revision()
    assert revision is None or len(revision.split("+")[0]) == 40


def test_revision_refreshes_after_edits_and_commits(tmp_path):
    import subprocess

    def git(*args):
        return subprocess.run(
            ["git", "-C", str(tmp_path), *args], check=True, capture_output=True, text=True
        ).stdout.strip()

    git("init")
    git("config", "user.email", "test@example.test")
    git("config", "user.name", "Test")
    (tmp_path / "code.py").write_text("v1")
    git("add", ".")
    git("commit", "-m", "Initialize.")
    first = current_source_revision(tmp_path)
    (tmp_path / "new.py").write_text("v2")
    assert current_source_revision(tmp_path) == first + "+dirty"
    git("add", ".")
    git("commit", "-m", "Change.")
    assert current_source_revision(tmp_path) != first
    assert "+dirty" not in current_source_revision(tmp_path)
