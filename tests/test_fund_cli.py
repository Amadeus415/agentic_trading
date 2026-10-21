from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from edgecraft.cli import main
from edgecraft.marketdata import MarketDataError, MarketDataRouter
from edgecraft.paper_fund import FundQuote, QuoteStatus
from edgecraft.schedule import scheduled_cycle_key

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "examples" / "fund.mandate.json"
EXAMPLE = ROOT / "examples" / "fund-cycle.starting.example.json"
PREDICTIONS = ROOT / "examples" / "fund.mandate.predictions.json"
PREDICTION_EXAMPLE = ROOT / "examples" / "fund-cycle.prediction.example.json"


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


def test_sized_run_turns_research_beliefs_into_trades_and_forecasts(tmp_path, capsys) -> None:
    common = ["--config", str(PREDICTIONS), "--ledger", str(tmp_path / "fund.db")]
    _run(["fund-init", *common], capsys)
    result = _run(
        [
            "fund-run",
            *common,
            "--input",
            str(PREDICTION_EXAMPLE),
            "--require-brain-journal",
            "--size-beliefs",
        ],
        capsys,
    )
    assert result["result"]["action"] == "trade"
    accepted = result["audit"]["sizing"]["accepted"]
    assert {row["instrument_id"] for row in accepted} == {
        "polymarket:900001:YES",
        "kalshi:KXEXAMPLE-26OCT20:NO",
    }
    # Unmeasured playbooks are sized at the prior trust, not the stated p_win.
    assert all(row["trust"] == "0.60" for row in accepted)
    # Highest annualized after-cost return is funded first.
    assert accepted[0]["instrument_id"] == "polymarket:900001:YES"
    assert Decimal(accepted[0]["annualized_return"]) > Decimal(accepted[1]["annualized_return"])
    report = _run(["fund-report", *common], capsys)
    assert report["forecast_skill"]["summary"]["forecasts"] == 2
    assert report["forecast_skill"]["variants"]["resolution_reading"]["trust"] == 0.6


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
    common = ["--config", str(PREDICTIONS), "--ledger", str(tmp_path / "fund.db")]
    _run(["fund-init", *common], capsys)

    def quote(_router, instrument_id, asset_class):
        if instrument_id.startswith("kalshi:"):
            raise MarketDataError("test TLS failure")
        return _contract_quote(instrument_id, "0.50")

    monkeypatch.setattr(MarketDataRouter, "quote", quote)
    result = _run(
        [
            "fund-snapshot",
            *common,
            "--instrument",
            "polymarket:1:YES:prediction",
            "--instrument",
            "kalshi:KX-1:NO:prediction",
            "--instrument",
            "AAPL:stock",
        ],
        capsys,
    )

    assert result["ok"] is True
    assert result["partial"] is True
    assert [item["instrument_id"] for item in result["quotes"]] == ["polymarket:1:YES"]
    assert {item["instrument_id"] for item in result["failures"]} == {"kalshi:KX-1:NO", "AAPL"}


def test_evolved_prompt_reaches_next_research_context_without_changing_parent(
    tmp_path, capsys
) -> None:
    common = ["--config", str(PREDICTIONS), "--ledger", str(tmp_path / "fund.db")]
    _run(["fund-init", *common], capsys)
    before = _run(["fund-context", *common], capsys)
    review = _run(["fund-postmortem", *common], capsys)
    review["proposals"] = [
        {
            "proposal_id": "source-test",
            "kind": "research_prompt_edit",
            "playbook_id": "resolution_reading",
            "rationale": "Check the resolution source's revision policy.",
            "patch": {"prompt": "Quote the source's revision policy before forecasting."},
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
    sleeve = next(row for row in after["sleeves"] if row["playbook_id"] == candidate_id)
    assert Decimal(sleeve["weight"]) == Decimal("0.25")  # four sleeves share one budget
    assert after["review"]["completed_reviews"] == 1
    assert "schema" in after["forecast_contract"]
    assert result["verification"]["ok"]


def test_fitted_packet_replays_original_size_after_policy_changes(tmp_path, capsys) -> None:
    config = tmp_path / "config.json"
    config.write_text(PREDICTIONS.read_text())
    common = ["--config", str(config), "--ledger", str(tmp_path / "fund.db")]
    _run(["fund-init", *common], capsys)
    packet = json.loads(PREDICTION_EXAMPLE.read_text())
    path = tmp_path / "packet.json"
    path.write_text(json.dumps(packet))
    first = _run(["fund-run", *common, "--input", str(path), "--size-beliefs"], capsys)
    assert first["result"]["fills"]
    changed = json.loads(config.read_text())
    changed["trading"]["kelly_fraction"] = "0.25"
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


def _contract_quote(instrument_id: str, price: str, *, settled: bool = False) -> FundQuote:
    now = datetime.now(UTC)
    book = (
        {}
        if settled
        else {
            "bids": [{"price": str(Decimal(price) - Decimal("0.01")), "size": "500"}],
            "asks": [{"price": str(Decimal(price) + Decimal("0.01")), "size": "500"}],
        }
    )
    return FundQuote.model_validate(
        {
            "quote_id": f"q-{instrument_id}-{now.timestamp()}",
            "instrument_id": instrument_id,
            "asset_class": "prediction",
            "price": price,
            "observed_at": now,
            "source_timestamp": now,
            "source_name": "test",
            "source_url": "https://example.test",
            "status": "settled" if settled else "open",
            "fee_rate": "0",
            "fee_exponent": 1,
            "fee_quantum": "0.00001",
            **book,
        }
    )


def test_forecast_skill_promotes_one_experiment_and_freezes_another(
    tmp_path, capsys, monkeypatch
) -> None:
    common = ["--config", str(PREDICTIONS), "--ledger", str(tmp_path / "fund.db")]
    _run(["fund-init", *common], capsys)
    marks: dict[str, FundQuote] = {}

    def quote(_router, instrument_id, asset_class):
        return marks[instrument_id]

    monkeypatch.setattr(MarketDataRouter, "quote", quote)
    monkeypatch.setattr(MarketDataRouter, "_cache", lambda _router, _quote: None)
    forecasts = []
    for index in range(40):
        market = f"polymarket:{1000 + index}"
        marks[f"{market}:YES"] = _contract_quote(f"{market}:YES", "0.50")
        wins = index % 2 == 0
        # The informed playbook leans the right way; the noise playbook leans at random.
        forecasts.append(
            {
                "market_id": market,
                "p_yes": "0.70" if wins else "0.30",
                "variant": "resolution_reading",
                "category": "signal",
            }
        )
        forecasts.append(
            {
                "market_id": market,
                "p_yes": "0.70" if index % 4 < 2 else "0.30",
                "variant": "consistency",
                "category": "noise",
            }
        )
    path = tmp_path / "forecasts.json"
    path.write_text(json.dumps({"fund_id": "edgecraft-predictions", "forecasts": forecasts}))
    recorded = _run(["fund-forecast", *common, "--input", str(path)], capsys)
    assert recorded["recorded"] == 80
    for index in range(40):
        market = f"polymarket:{1000 + index}"
        marks[f"{market}:YES"] = _contract_quote(
            f"{market}:YES", "1" if index % 2 == 0 else "0", settled=True
        )
    scored = _run(["fund-forecast-score", *common, "--limit", "100"], capsys)
    assert scored["resolved"] == 40
    review = _run(["fund-postmortem", *common], capsys)
    assert any("resolution_reading: trust" in line for line in review["what_worked"])
    review_path = tmp_path / "review.json"
    review_path.write_text(json.dumps(review))
    evolved = _run(["fund-evolve", *common, "--postmortem", str(review_path)], capsys)
    statuses = {row["playbook_id"]: row["to_status"] for row in evolved["transitions"]}
    assert statuses == {"resolution_reading": "active", "consistency": "frozen"}
    context = _run(["fund-context", *common], capsys)
    skill = context["forecast_skill"]["variants"]
    assert skill["resolution_reading"]["skill"] > 0
    assert skill["resolution_reading"]["trust"] > 0.6
    assert skill["consistency"]["estimated_trust"] <= 0.05
    assert context["forecast_skill"]["head_to_head"][0]["left"] == "consistency"
    assert context["forecast_skill"]["head_to_head"][0]["left_advantage"] < 0
    # Research is steered to the playbook with no settled forecasts and away from the
    # category that lost to the market; measured and frozen playbooks need no more.
    focus = context["research_focus"]
    assert focus["undertested_playbooks"] == {"long_tail_news": 0}
    assert focus["weak_categories"] == ["noise"]
    assert evolved["verification"]["ok"]


def test_monitor_bridges_a_blip_with_a_fresh_cached_mark_but_not_an_outage(
    tmp_path, capsys, monkeypatch
) -> None:
    common = ["--config", str(PREDICTIONS), "--ledger", str(tmp_path / "fund.db")]
    _run(["fund-init", *common], capsys)
    fund_run = ["fund-run", *common, "--input", str(PREDICTION_EXAMPLE)]
    _run([*fund_run, "--require-brain-journal", "--size-beliefs"], capsys)
    monkeypatch.chdir(tmp_path)  # The monitor's quote cache lives under ./state/marks.
    clock = iter(datetime.now(UTC) + timedelta(seconds=step - 60) for step in range(60))
    down: set[str] = set()

    def quote(router, instrument_id, asset_class):
        if any(instrument_id.startswith(venue) for venue in down):
            raise MarketDataError("test connection reset")
        now = next(clock)
        # Pending marks never trigger exits, so the test does not depend on today's date.
        fresh = _contract_quote(instrument_id, "0.40").model_copy(
            update={"observed_at": now, "source_timestamp": now, "status": QuoteStatus.PENDING}
        )
        router._cache(fresh)
        return fresh

    monkeypatch.setattr(MarketDataRouter, "quote", quote)
    assert _run(["monitor", *common], capsys)["applied"] is True
    down.add("kalshi:")
    blip = _run(["monitor", *common], capsys)
    assert blip["applied"] is True
    assert blip["failures"] == []
    down.add("polymarket:")
    outage = _run(["monitor", *common], capsys)
    assert (outage["applied"], outage["reason"]) == (False, "mark_fetch_failed")
    assert len(outage["failures"]) == 2
