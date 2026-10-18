from __future__ import annotations

import json
import math
import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from edgecraft.forecasts import (
    ForecastFile,
    favorite_bias_probability,
    fit_gamma,
    forecast_skill,
    journal_forecasts,
    record_research_forecasts,
    score_forecasts,
    trust_map,
)
from edgecraft.paper_fund import (
    DecisionAction,
    DecisionJournal,
    FundDecision,
    FundEvidence,
    FundHypothesis,
    FundMandate,
    FundQuote,
    PaperFundLedger,
)
from edgecraft.policy import TradingPolicy

NOW = datetime(2026, 10, 18, 15, tzinfo=UTC)
MANDATE = FundMandate.model_validate(
    json.loads(Path("examples/fund.mandate.predictions.json").read_text())["mandate"]
)


def _quote(instrument: str, price: str, *, settled: bool = False, at: datetime = NOW) -> FundQuote:
    return FundQuote(
        quote_id=f"q-{instrument}-{at.timestamp()}",
        instrument_id=instrument,
        asset_class="prediction",
        price=price,
        observed_at=at,
        source_timestamp=at,
        source_name="test",
        source_url="https://example.test",
        status="settled" if settled else "open",
    )


class Router:
    def __init__(self):
        self.marks: dict[str, FundQuote] = {}

    def quote(self, instrument, asset):
        if instrument not in self.marks:
            raise RuntimeError("closed market is not confirmed resolved")
        return self.marks[instrument]

    def latest_cached_quote(self, instrument, at_or_before=None):
        raise RuntimeError("no cache")


def _ledger(tmp_path) -> PaperFundLedger:
    ledger = PaperFundLedger(tmp_path / "fund.db")
    ledger.initialize("fund", MANDATE)
    return ledger


def test_favorite_bias_curve_lifts_favorites_and_sinks_longshots_symmetrically():
    favorite = favorite_bias_probability(Decimal("0.95"), Decimal("1.15"))
    longshot = favorite_bias_probability(Decimal("0.05"), Decimal("1.15"))
    assert favorite > Decimal("0.95")
    assert favorite + longshot == pytest.approx(Decimal("1"), abs=Decimal("0.000002"))
    assert favorite_bias_probability(Decimal("0.5"), Decimal("1.5")) == Decimal("0.5")


def test_gamma_fit_recovers_a_known_bias():
    rng = random.Random(7)
    rows = []
    for _ in range(4000):
        market = rng.uniform(0.03, 0.97)
        truth = 1 / (1 + math.exp(-1.4 * math.log(market / (1 - market))))
        rows.append((market, int(rng.random() < truth)))
    assert fit_gamma(rows) == pytest.approx(1.4, abs=0.15)


def test_forecasts_are_stamped_with_code_owned_prices_and_settled_markets_are_refused(tmp_path):
    router = Router()
    router.marks["polymarket:1:YES"] = _quote("polymarket:1:YES", "0.40")
    router.marks["polymarket:2:YES"] = _quote("polymarket:2:YES", "1", settled=True)
    forecasts = ForecastFile.model_validate(
        {
            "fund_id": "fund",
            "forecasts": [
                {"market_id": "polymarket:1:YES", "p_yes": "0.70", "variant": "resolution_reading"},
                {"market_id": "polymarket:2", "p_yes": "0.99", "variant": "resolution_reading"},
            ],
        }
    )
    with _ledger(tmp_path) as ledger:
        result = record_research_forecasts(ledger, "fund", forecasts, router, now=NOW)
        assert result["recorded"] == 1
        assert "settled" in result["failures"][0]["detail"]
        batch = ledger.list_events("fund")[-1].payload["forecasts"][0]
    assert batch["market_id"] == "polymarket:1"
    assert batch["market_yes"] == "0.40"


def _forecast_and_resolve(ledger, router, rows, variant="resolution_reading"):
    forecasts = []
    for index, (p_yes, market, _outcome) in enumerate(rows):
        key = f"kalshi:M{index}"
        router.marks[f"{key}:YES"] = _quote(f"{key}:YES", market)
        forecasts.append({"market_id": key, "p_yes": p_yes, "variant": variant})
    record_research_forecasts(
        ledger, "fund", ForecastFile(fund_id="fund", forecasts=forecasts), router, now=NOW
    )
    for index, (_, _, outcome) in enumerate(rows):
        key = f"kalshi:M{index}"
        if outcome is not None:
            router.marks[f"{key}:YES"] = _quote(f"{key}:YES", str(outcome), settled=True)
    return score_forecasts(ledger, "fund", router, limit=500)


def test_informative_forecasts_earn_trust_and_refreshes_do_not_add_samples(tmp_path):
    router = Router()
    rows = [("0.80", "0.50", 1), ("0.20", "0.50", 0)] * 20
    with _ledger(tmp_path) as ledger:
        scored = _forecast_and_resolve(ledger, router, rows)
        assert scored["resolved"] == 40
        # A refresh of the same contract and variant must not count twice.
        ledger.record_operational_event(
            "fund",
            "forecast_batch",
            {
                "source": "research",
                "forecasts": [
                    {
                        "market_id": "kalshi:M0",
                        "p_yes": "0.99",
                        "market_yes": "0.5",
                        "observed_at": NOW.isoformat(),
                        "variant": "resolution_reading",
                        "category": "uncategorized",
                        "question": "",
                        "resolves_at": None,
                    }
                ],
            },
        )
        skill = forecast_skill(ledger, "fund", TradingPolicy())
    metrics = skill["variants"]["resolution_reading"]
    assert metrics["forecasts"] == 40
    assert metrics["skill"] > 0
    assert metrics["estimated_trust"] >= 1
    assert metrics["trust"] > 0.8
    assert trust_map(skill, TradingPolicy())["resolution_reading"] == Decimal(str(metrics["trust"]))


def test_drift_toward_the_forecast_is_fast_evidence_before_resolution(tmp_path):
    router = Router()
    rows = [("0.70", "0.50", None)] * 12
    with _ledger(tmp_path) as ledger:
        _forecast_and_resolve(ledger, router, rows)
        early = NOW + timedelta(hours=1)
        for index in range(12):
            key = f"kalshi:M{index}:YES"
            router.marks[key] = _quote(key, "0.40", at=early)
        score_forecasts(ledger, "fund", router, limit=500, now=early)
        # Marks within the first 12 hours are noise and must not move trust.
        assert forecast_skill(ledger, "fund")["variants"]["resolution_reading"]["trust_basis"] == (
            "prior"
        )
        later = NOW + timedelta(hours=13)
        for index in range(12):
            key = f"kalshi:M{index}:YES"
            router.marks[key] = _quote(key, "0.60", at=later)
        score_forecasts(ledger, "fund", router, limit=500, now=later)
        metrics = forecast_skill(ledger, "fund")["variants"]["resolution_reading"]
    assert metrics["trust_basis"] == "drift"
    assert metrics["drift_trust"] == 0.5
    assert metrics["mean_drift_toward_forecast"] == 0.1


def test_uninformed_forecasts_fall_to_zero_estimated_trust(tmp_path):
    router = Router()
    rows = [("0.80", "0.50", 0), ("0.20", "0.50", 1), ("0.80", "0.50", 1), ("0.20", "0.50", 0)]
    with _ledger(tmp_path) as ledger:
        _forecast_and_resolve(ledger, router, rows * 10)
        metrics = forecast_skill(ledger, "fund")["variants"]["resolution_reading"]
    assert metrics["skill"] < 0
    assert metrics["estimated_trust"] <= 0.05


def test_journal_beliefs_become_yes_forecasts():
    hypothesis = FundHypothesis(
        instrument_id="kalshi:KX-1:NO",
        stance="long",
        statement="NO wins",
        mechanism="calendar",
        catalysts=("release",),
        falsifiers=("early release",),
        expected_horizon_hours=24,
        confidence="0.9",
        p_win="0.9",
        playbook_id="long_tail_news",
        driver="calendar",
        target_price="0.99",
        invalidation_price="0.5",
        evidence_ids=("e",),
    )
    decision = FundDecision(
        decision_id="d",
        fund_id="fund",
        cycle_key="c",
        as_of=NOW,
        action=DecisionAction.HOLD,
        thesis="t",
        evidence=(
            FundEvidence(
                evidence_id="e",
                observed_at=NOW,
                source_timestamp=NOW,
                source_name="s",
                source_url="https://example.test",
                claim="c",
            ),
        ),
        journal=DecisionJournal(
            market_regime="m",
            opportunity_set="o",
            portfolio_intent="p",
            what_changed="w",
            hypotheses=(hypothesis,),
        ),
    )
    (row,) = journal_forecasts(decision, [_quote("kalshi:KX-1:NO", "0.85")])
    assert row["market_id"] == "kalshi:KX-1"
    assert Decimal(row["p_yes"]) == Decimal("0.1")
    assert Decimal(row["market_yes"]) == Decimal("0.15")
    assert row["variant"] == "long_tail_news"
