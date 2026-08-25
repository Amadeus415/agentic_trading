from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from edgecraft.cli import main

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "examples" / "fund.mandate.json"
EXAMPLE = ROOT / "examples" / "fund-cycle.starting.example.json"


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> dict:
    main(argv)
    return json.loads(capsys.readouterr().out)


def test_fund_cli_initializes_runs_reports_and_verifies(tmp_path, capsys) -> None:
    ledger = tmp_path / "fund.db"
    common = ["--config", str(CONFIG), "--ledger", str(ledger)]

    first = _run(["fund-init", *common], capsys)
    second = _run(["fund-init", *common], capsys)
    context = _run(["fund-context", *common], capsys)
    cycle = _run(
        ["fund-run", *common, "--input", str(EXAMPLE), "--require-brain-journal"],
        capsys,
    )
    shown = _run(["fund-show", *common, "--history", "--events"], capsys)
    verification = _run(["fund-verify", *common], capsys)
    cycle_key = cycle["result"]["cycle_key"]
    cycle_detail = _run(["fund-cycle", *common, "--cycle-key", cycle_key], capsys)
    audited = _run(["fund-cycle", *common, "--cycle-key", cycle_key, "--audit"], capsys)

    assert first["initialized"] is True
    assert second["initialized"] is False
    assert context["state"]["cash"] == "1000.00"
    assert context["growth_objective"]["target_nav"] == "100000.00"
    assert context["growth_objective"]["stage"] == "bootstrap"
    assert context["growth_objective"]["target_multiple"] == "100"
    assert "decision_schema" in context["input_contract"]
    assert context["brain"]["schema_version"] == "edgecraft.fund-brain.v1"
    assert cycle["paper_only"] is True
    assert cycle["result"]["state"]["cycle_count"] == 1
    assert cycle["result"]["audit"]["risk"]["approved"] is True
    assert cycle["result"]["audit"]["runtime"]["input_sha256"]
    assert cycle["audit"]["request_digest"] == cycle["result"]["request_digest"]
    assert {fill["asset_class"] for fill in cycle["result"]["fills"]} == {
        "stock",
        "crypto",
        "prediction",
    }
    assert shown["cycle_count"] == 1
    assert len(shown["brain"]["instruments"]) == 3
    assert len(shown["brain"]["recent_cycles"]) == 1
    assert Decimal(shown["growth_objective"]["remaining_multiple"]) > 0
    assert shown["history"]["initial_cash"] == "1000.00"
    assert shown["history"]["simulated_fill_count"] == 3
    assert shown["history"]["history"][0]["cycle_key"] == "example-start-2026-08-06"
    assert shown["events"]
    assert verification["ok"] is True
    assert cycle_detail["cycle"]["decision"]["cycle_key"] == cycle_key
    assert "audit" not in cycle_detail
    assert audited["audit"]["audit_gaps"] == []
    assert audited["audit"]["reconciliation"]["has_audit_sidecar"] is True
    assert audited["audit"]["events"]


def test_fund_cli_rejects_noncurrent_scheduled_input(tmp_path, capsys) -> None:
    ledger = tmp_path / "fund.db"
    stale_input = tmp_path / "stale.json"
    payload = json.loads(EXAMPLE.read_text())
    payload["decision"]["as_of"] = "2020-01-01T20:00:00Z"
    for evidence in payload["decision"]["evidence"]:
        evidence["observed_at"] = "2020-01-01T19:55:00Z"
        evidence["source_timestamp"] = "2020-01-01T19:50:00Z"
    for quote in payload["quotes"]:
        quote["observed_at"] = "2020-01-01T19:59:00Z"
        quote["source_timestamp"] = "2020-01-01T19:58:00Z"
    stale_input.write_text(json.dumps(payload))
    _run(
        ["fund-init", "--config", str(CONFIG), "--ledger", str(ledger)],
        capsys,
    )

    with pytest.raises(SystemExit) as exc:
        main(
            [
                "fund-run",
                "--config",
                str(CONFIG),
                "--ledger",
                str(ledger),
                "--input",
                str(stale_input),
                "--require-as-of-today",
            ]
        )

    assert exc.value.code == 2
    error = json.loads(capsys.readouterr().err)
    assert "is not today's UTC date" in error["detail"]
