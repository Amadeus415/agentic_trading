from datetime import UTC, datetime

import pytest

from edgecraft.readme_dashboard import (
    END_MARKER,
    START_MARKER,
    build_console_markdown,
    update_readme,
)


def _health() -> dict:
    return {
        "status": "ready",
        "reasons": ["private warning mentioning AMD and account 123"],
        "last_success_at": "2026-07-21T18:10:08+00:00",
        "snapshot": {
            "runs_by_status": {"completed": 1, "held": 1},
            "proposals_by_approval": {"approved": 1, "rejected": 2},
            "order_events_by_type": {"placed": 1, "filled": 1},
            "unresolved_order_count": 0,
            "trading_halted": False,
        },
    }


def test_console_reports_only_aggregate_operational_evidence() -> None:
    console = build_console_markdown(
        _health(),
        [{"status": "completed", "updated_at": "2026-07-21T18:10:08+00:00"}],
        ["live"],
        generated_at=datetime(2026, 7, 21, 23, 0, tzinfo=UTC),
    )

    assert "**READY**" in console
    assert "| Orders placed | **1**" in console
    assert "| Fills recorded | **1**" in console
    assert "Control-plane warnings: **1**" in console
    assert "A test, proposal, or permit is not counted as a fill." in console
    assert "AMD" not in console
    assert "account 123" not in console


def test_update_readme_replaces_only_the_console(tmp_path) -> None:
    readme = tmp_path / "README.md"
    readme.write_text(f"before\n{START_MARKER}\nold\n{END_MARKER}\nafter\n")
    console = f"{START_MARKER}\nnew\n{END_MARKER}"

    assert update_readme(readme, console) is True
    assert readme.read_text() == f"before\n{console}\nafter\n"
    assert update_readme(readme, console) is False


def test_update_readme_requires_one_marker_pair(tmp_path) -> None:
    readme = tmp_path / "README.md"
    readme.write_text("no generated console")

    with pytest.raises(ValueError, match="exactly one"):
        update_readme(readme, "unused")
