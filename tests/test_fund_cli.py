from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from edgecraft.cli import main
from edgecraft.schedule import scheduled_cycle_key

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
    assert "growth_objective" not in context
    assert "growth_objective" not in context["mandate"]
    assert "decision_schema" in context["input_contract"]
    assert context["brain"]["schema_version"] == "edgecraft.fund-brain.v1"
    assert context["brain"]["activity"]["style"] == "short_term_active"
    assert context["schedule"]["max_hypothesis_horizon_hours"] == 72
    assert any("after-cost edge" in rule for rule in context["input_contract"]["rules"])
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


def test_fund_cli_report_postmortem_and_alerts(tmp_path, capsys) -> None:
    ledger = tmp_path / "fund.db"
    common = ["--config", str(CONFIG), "--ledger", str(ledger)]
    _run(["fund-init", *common], capsys)
    _run(["fund-run", *common, "--input", str(EXAMPLE), "--require-brain-journal"], capsys)
    report = _run(["fund-report", *common], capsys)
    postmortem = _run(["fund-postmortem", *common], capsys)
    alerts = _run(["fund-alerts", *common], capsys)
    assert report["schema_version"] == "edgecraft.fund-report.v1"
    assert report["summary"]["cycles"] == 1
    assert report["benchmarks"]["spy_buy_and_hold"]["status"] == "unavailable"
    assert postmortem["schema_version"] == "edgecraft.postmortem.v1"
    assert postmortem["fund_id"] == "edgecraft-1k"
    assert alerts["ok"] is True
    assert alerts["alerts"] == []


def test_fund_cycle_key_prints_current_session(capsys) -> None:
    payload = _run(["fund-cycle-key"], capsys)
    expected = scheduled_cycle_key()
    assert payload["ok"] is True
    assert payload["cycle_key"] == expected
    assert payload["input_path"] == f"state/fund-inputs/{expected}.json"

    main(["fund-cycle-key", "--plain"])
    assert capsys.readouterr().out.strip() == expected
