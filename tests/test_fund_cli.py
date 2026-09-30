from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from edgecraft.cli import main
from edgecraft.marketdata import MarketDataError, MarketDataRouter
from edgecraft.paper_fund import FundQuote
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


def test_sized_run_derives_orders_and_action_from_directional_research(tmp_path, capsys) -> None:
    ledger = tmp_path / "fund.db"
    input_path = tmp_path / "research-only.json"
    payload = json.loads(EXAMPLE.read_text())
    payload["decision"]["action"] = "hold"
    payload["decision"]["orders"] = []
    input_path.write_text(json.dumps(payload))
    common = ["--config", str(CONFIG), "--ledger", str(ledger)]
    _run(["fund-init", *common], capsys)

    result = _run(
        [
            "fund-run",
            *common,
            "--input",
            str(input_path),
            "--require-brain-journal",
            "--size-beliefs",
        ],
        capsys,
    )

    assert result["result"]["action"] == "trade"
    assert {fill["instrument_id"] for fill in result["result"]["fills"]} == {"BTC-USD"}
    assert result["audit"]["sizing"]["accepted"][0]["instrument_id"] == "BTC-USD"


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


def test_fund_snapshot_isolates_optional_candidate_provider_failure(
    tmp_path, capsys, monkeypatch
) -> None:
    ledger = tmp_path / "fund.db"
    common = ["--config", str(CONFIG), "--ledger", str(ledger)]
    _run(["fund-init", *common], capsys)

    def quote(_router, instrument_id, asset_class):
        if instrument_id == "BTC-USD":
            raise MarketDataError("test TLS failure")
        now = datetime(2026, 9, 14, 20, tzinfo=UTC)
        return FundQuote(
            quote_id="q-aapl",
            instrument_id=instrument_id,
            asset_class=asset_class,
            price="200",
            observed_at=now,
            source_timestamp=now,
            source_name="test",
            source_url="https://example.test",
        )

    monkeypatch.setattr(MarketDataRouter, "quote", quote)
    result = _run(
        [
            "fund-snapshot",
            *common,
            "--instrument",
            "AAPL:stock",
            "--instrument",
            "BTC-USD:crypto",
        ],
        capsys,
    )

    assert result["ok"] is True
    assert result["partial"] is True
    assert [item["instrument_id"] for item in result["quotes"]] == ["AAPL"]
    assert result["failures"] == [{"instrument_id": "BTC-USD", "detail": "test TLS failure"}]


def test_evolved_prompt_reaches_next_research_context_without_changing_parent(
    tmp_path, capsys
) -> None:
    common = ["--config", str(CONFIG), "--ledger", str(tmp_path / "fund.db")]
    _run(["fund-init", *common], capsys)
    before = _run(["fund-context", *common], capsys)
    review = _run(["fund-postmortem", *common], capsys)
    review["proposals"] = [
        {
            "proposal_id": "volume-test",
            "kind": "research_prompt_edit",
            "playbook_id": "crypto_momentum",
            "rationale": "Check volume confirmation.",
            "patch": {"prompt": "Require independently sourced volume confirmation."},
            "backtestable": False,
        }
    ]
    review_path = tmp_path / "review.json"
    review_path.write_text(json.dumps(review))
    result = _run(["fund-evolve", *common, "--postmortem", str(review_path)], capsys)
    after = _run(["fund-context", *common], capsys)
    candidate_id = result["transitions"][0]["playbook_id"]
    candidate = next(book for book in after["playbooks"] if book["spec"]["id"] == candidate_id)
    assert candidate["prompt"] == review["proposals"][0]["patch"]["prompt"]
    assert all(book in after["playbooks"] for book in before["playbooks"])
    assert (
        next(sleeve for sleeve in after["sleeves"] if sleeve["playbook_id"] == candidate_id)[
            "weight"
        ]
        == "0.30"
    )
    assert after["review"]["completed_reviews"] == 1
    assert result["verification"]["ok"]


def test_fitted_packet_replays_original_size_after_policy_changes(tmp_path, capsys) -> None:
    config = tmp_path / "config.json"
    config.write_text((ROOT / "examples/fund.mandate.aggressive.json").read_text())
    common = ["--config", str(config), "--ledger", str(tmp_path / "fund.db")]
    _run(["fund-init", *common], capsys)
    packet = json.loads(EXAMPLE.read_text())
    packet["decision"]["fund_id"] = "edgecraft-aggressive"
    packet["decision"]["action"] = "hold"
    packet["decision"]["orders"] = []
    packet["decision"]["journal"]["hypotheses"] = [packet["decision"]["journal"]["hypotheses"][1]]
    packet["quotes"] = [packet["quotes"][1]]
    path = tmp_path / "packet.json"
    path.write_text(json.dumps(packet))
    first = _run(["fund-run", *common, "--input", str(path), "--size-beliefs"], capsys)
    assert first["result"]["fills"]
    changed = json.loads(config.read_text())
    changed["trading"]["kelly_fraction"] = "0.5"
    config.write_text(json.dumps(changed))
    replay = _run(["fund-run", *common, "--input", str(path), "--size-beliefs"], capsys)
    assert replay["result"]["replayed"]
    assert replay["result"]["fills"] == first["result"]["fills"]
    assert replay["result"]["audit"] == first["result"]["audit"]
    assert _run(["fund-show", *common], capsys)["cycle_count"] == 1
    packet["decision"]["thesis"] = "Changed request under the same identity."
    path.write_text(json.dumps(packet))
    with pytest.raises(SystemExit):
        _run(["fund-run", *common, "--input", str(path), "--size-beliefs"], capsys)
    assert _run(["fund-verify", *common], capsys)["ok"]


def test_forward_experiment_earns_and_loses_budget_from_actual_paper_fills(
    tmp_path, capsys
) -> None:
    from datetime import timedelta

    common = [
        "--config",
        str(ROOT / "examples/fund.mandate.aggressive.json"),
        "--ledger",
        str(tmp_path / "fund.db"),
    ]
    _run(["fund-init", *common], capsys)
    review = _run(["fund-postmortem", *common], capsys)
    review["proposals"] = [
        {
            "proposal_id": "forward-test",
            "kind": "research_prompt_edit",
            "playbook_id": "crypto_momentum",
            "rationale": "Test a revised catalyst prompt.",
            "patch": {"prompt": "Use direct volume evidence."},
            "backtestable": False,
        }
    ]
    review_path = tmp_path / "review.json"
    review_path.write_text(json.dumps(review))
    evolved = _run(["fund-evolve", *common, "--postmortem", str(review_path)], capsys)
    version = evolved["transitions"][0]["playbook_id"]
    packet = json.loads(EXAMPLE.read_text())
    packet["decision"]["fund_id"] = "edgecraft-aggressive"
    packet["decision"]["orders"] = []
    packet["decision"]["action"] = "hold"
    belief = packet["decision"]["journal"]["hypotheses"][1]
    belief.update(playbook_id=version, p_win="0.60", target_price="110", invalidation_price="95")
    packet["decision"]["journal"]["hypotheses"] = [belief]
    packet["quotes"] = [packet["quotes"][1]]
    packet["decision"]["evidence"] = [packet["decision"]["evidence"][1]]
    packet_path = tmp_path / "packet.json"
    started = datetime.now(UTC)
    for trade in range(11):
        for phase, price, stance in [
            (0, "100", "long"),
            (1, "101" if trade < 10 else "80", "exit"),
        ]:
            at = (started + timedelta(minutes=2 * trade + phase)).isoformat()
            packet["decision"].update(
                as_of=at, cycle_key=f"test-{trade}-{phase}", decision_id=f"d-{trade}-{phase}"
            )
            packet["quotes"][0].update(price=price, observed_at=at, source_timestamp=at)
            packet["decision"]["evidence"][0].update(observed_at=at, source_timestamp=at)
            belief["stance"] = stance
            packet_path.write_text(json.dumps(packet))
            result = _run(
                ["fund-run", *common, "--input", str(packet_path), "--size-beliefs"], capsys
            )
            assert len(result["result"]["fills"]) == 1
        if trade == 9:
            context = _run(["fund-context", *common], capsys)
            sleeve = next(row for row in context["sleeves"] if row["playbook_id"] == version)
            assert sleeve["status"] == "active"
            assert Decimal(sleeve["weight"]) > Decimal("0.60")
    review = _run(["fund-postmortem", *common], capsys)
    review_path.write_text(json.dumps(review))
    frozen = _run(["fund-evolve", *common, "--postmortem", str(review_path)], capsys)
    assert any(
        row["playbook_id"] == version and row["to_status"] == "frozen"
        for row in frozen["transitions"]
    )
    report = _run(["fund-report", *common], capsys)
    assert report["summary"]["closed_trades"] == 11
    assert report["playbook_statuses"][version] == "frozen"
    context = _run(["fund-context", *common], capsys)
    assert next(row for row in context["sleeves"] if row["playbook_id"] == version)["weight"] == "0"
    assert frozen["verification"]["ok"]
