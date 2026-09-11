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
