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
    status = _run(["fund-status", *common], capsys)
    brain = _run(["fund-brain", *common], capsys)
    performance = _run(["fund-performance", *common], capsys)
    verification = _run(["fund-verify", *common], capsys)
    cycle_key = cycle["result"]["cycle_key"]
    cycle_detail = _run(["fund-cycle", *common, "--cycle-key", cycle_key], capsys)
    audit = _run(["fund-audit", *common, "--cycle-key", cycle_key], capsys)

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
    assert status["cycle_count"] == 1
    assert len(status["brain"]["instruments"]) == 3
    assert len(brain["brain"]["recent_cycles"]) == 1
    assert Decimal(status["growth_objective"]["remaining_multiple"]) > 0
    assert performance["initial_cash"] == "1000.00"
    assert performance["simulated_fill_count"] == 3
    assert performance["history"][0]["cycle_key"] == "example-start-2026-08-06"
    assert verification["ok"] is True
    assert cycle_detail["cycle"]["decision"]["cycle_key"] == cycle_key
    assert audit["audit_gaps"] == []
    assert audit["reconciliation"]["ledger_ok"] is True
    assert audit["events"]


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
