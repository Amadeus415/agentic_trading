from __future__ import annotations

import json
from pathlib import Path

from edgecraft.attribution import build_fund_report
from edgecraft.paper_fund import (
    CycleRuntimeMetadata,
    FundDecision,
    FundMandate,
    FundQuote,
    PaperFundLedger,
)

ROOT = Path(__file__).resolve().parents[1]


def test_report_scores_only_observed_outcomes_and_retains_runtime(tmp_path: Path) -> None:
    packet = json.loads((ROOT / "examples/fund-cycle.starting.example.json").read_text())
    decision = FundDecision.model_validate(packet["decision"])
    quotes = [FundQuote.model_validate(item) for item in packet["quotes"]]
    mandate = FundMandate()

    with PaperFundLedger(tmp_path / "fund.db") as ledger:
        ledger.initialize(decision.fund_id, mandate)
        ledger.execute_cycle(
            decision,
            quotes,
            runtime=CycleRuntimeMetadata(
                edgecraft_version="test",
                mandate_digest="test",
                model="test-model",
                reasoning_effort="high",
                prompt_version="prompt-v1",
            ),
        )
        report = build_fund_report(ledger, decision.fund_id, mandate)

    assert report["schema_version"] == "edgecraft.fund-report.v1"
    assert report["summary"]["cycles"] == 1
    assert report["summary"]["hypotheses"] == 3
    assert report["summary"]["scored_hypotheses"] == 0
    assert report["summary"]["closed_trades"] == 0
    assert {row["model"] for row in report["attribution"]} == {"test-model"}
    assert report["cuts"]["asset_class"]
    assert report["benchmarks"]["spy_buy_and_hold"]["status"] == "unavailable"


def test_partial_exits_count_as_one_learning_outcome() -> None:
    from edgecraft.attribution import _round_trips, _sizing_calibration

    def cycle(at, fills):
        return {
            "as_of": at,
            "cycle_key": at,
            "decision": {
                "journal": {
                    "hypotheses": [
                        {
                            "instrument_id": "A",
                            "playbook_id": "version_2",
                            "p_win": "0.65",
                        }
                    ]
                }
            },
            "fills": fills,
        }

    def fill(side, quantity, fee, pnl):
        return {
            "instrument_id": "A",
            "asset_class": "stock",
            "side": side,
            "quantity": quantity,
            "fee": fee,
            "realized_pnl": pnl,
        }

    opened = cycle("2026-09-01T15:00:00Z", [fill("buy", "10", "1", "0")])
    partial = cycle("2026-09-01T16:00:00Z", [fill("sell", "4", "0.4", "5")])
    closed = cycle("2026-09-01T17:00:00Z", [fill("sell", "6", "0.6", "-2")])
    assert _round_trips([opened, partial]) == []
    trades = _round_trips([opened, partial, closed])
    assert len(trades) == 1
    assert trades[0]["quantity"] == "10"
    assert trades[0]["realized_pnl_after_cost"] == "2.0"
    assert _sizing_calibration(trades, 20) == [
        {
            "playbook_id": "version_2",
            "bucket": "60-70%",
            "count": 1,
            "realized_win_rate": "1",
        }
    ]


def test_prediction_short_calibrates_settlement_probability_not_trade_profit() -> None:
    from edgecraft.attribution import _round_trips, _sizing_calibration

    def cycle(at, fill):
        return {
            "as_of": at,
            "cycle_key": at,
            "decision": {
                "journal": {
                    "hypotheses": [
                        {
                            "instrument_id": "binary:YES",
                            "playbook_id": "parent",
                            "p_win": "0.15",
                        }
                    ]
                }
            },
            "fills": [fill],
        }

    common = {
        "instrument_id": "binary:YES",
        "asset_class": "prediction",
        "quantity": "10",
        "fee": "0",
        "playbook_id": "experiment",
    }
    opened = cycle("2026-09-01T15:00:00Z", {**common, "side": "short", "realized_pnl": "0"})
    settled = cycle(
        "2026-09-01T16:00:00Z",
        {**common, "side": "settle", "realized_pnl": "4", "execution_price": "0"},
    )
    trades = _round_trips([opened, settled])
    assert trades[0]["won"]
    assert trades[0]["playbook_id"] == "experiment"
    assert not trades[0]["probability_outcome"]
    assert _sizing_calibration(trades, 20)[0]["realized_win_rate"] == "0"


def test_report_retains_flat_candidate_without_scoring_it(tmp_path: Path) -> None:
    packet = json.loads((ROOT / "examples/fund-cycle.starting.example.json").read_text())
    rejected = dict(packet["decision"]["journal"]["hypotheses"][0])
    rejected.update(
        {
            "instrument_id": "MSFT",
            "stance": "flat",
            "statement": "The researched candidate did not clear costs.",
            "evidence_ids": ["example-rejected"],
        }
    )
    packet["decision"]["journal"]["hypotheses"].append(rejected)
    packet["decision"]["evidence"].append(
        {
            **packet["decision"]["evidence"][0],
            "evidence_id": "example-rejected",
            "instrument_ids": ["MSFT"],
        }
    )
    decision = FundDecision.model_validate(packet["decision"])
    quotes = [FundQuote.model_validate(item) for item in packet["quotes"]]

    with PaperFundLedger(tmp_path / "fund.db") as ledger:
        ledger.initialize(decision.fund_id, FundMandate())
        ledger.execute_cycle(decision, quotes)
        report = build_fund_report(ledger, decision.fund_id, FundMandate())

    flat = next(row for row in report["attribution"] if row["instrument_id"] == "MSFT")
    assert flat["outcome"] == "rejected"
    assert flat["scored"] is False
    assert report["summary"]["hypotheses"] == 4
    assert report["summary"]["scored_hypotheses"] == 0
