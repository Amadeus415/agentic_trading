from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from edgecraft.paper_fund import (
    CycleRuntimeMetadata,
    FundDecision,
    FundMandate,
    FundQuote,
    PaperFundLedger,
)
from edgecraft.results import (
    _close_time,
    brier_score,
    build_results,
    calibration_bins,
    drawdowns,
    extract_ledger,
    first_market_forecasts,
    first_theses,
    max_drawdown,
    resolved_outcome,
    time_weighted_mean,
)

ROOT = Path(__file__).resolve().parents[1]


def test_brier_score_is_mean_squared_error():
    assert brier_score([1.0, 0.0], [1.0, 0.0]) == 0
    assert brier_score([0.5, 0.5], [1.0, 0.0]) == pytest.approx(0.25)
    assert brier_score([0.9, 0.2, 0.6], [1.0, 0.0, 0.0]) == pytest.approx((0.01 + 0.04 + 0.36) / 3)
    with pytest.raises(ValueError):
        brier_score([], [])
    with pytest.raises(ValueError):
        brier_score([0.5], [1.0, 0.0])


def test_calibration_bins_group_by_stated_probability():
    rows = calibration_bins([0.05, 0.08, 0.55, 0.58, 0.61, 1.0], [0, 0, 1, 0, 1, 1])
    assert [(r["lower"], r["count"]) for r in rows] == [(0.0, 2), (0.5, 2), (0.6, 1), (0.9, 1)]
    assert rows[0]["mean_forecast"] == pytest.approx(0.065)
    assert rows[1]["hit_rate"] == pytest.approx(0.5)
    assert rows[-1]["upper"] == 1.0  # a forecast of exactly 1.0 lands in the top bin
    with pytest.raises(ValueError):
        calibration_bins([1.2], [1])


def test_drawdown_tracks_the_running_peak():
    navs = [1000, 1100, 990, 1050, 880, 1200, 1150]
    assert drawdowns(navs) == pytest.approx([0, 0, 0.1, 0.0454545, 0.2, 0, 0.0416667], rel=1e-5)
    deepest = max_drawdown(navs)
    assert deepest["depth"] == pytest.approx(0.2)
    assert (deepest["peak_index"], deepest["trough_index"]) == (1, 4)
    assert max_drawdown([1000, 1010, 1020])["depth"] == 0


def test_time_weighted_mean_holds_each_value_until_the_next_mark():
    times = [datetime(2026, 9, 1, h, tzinfo=UTC) for h in (0, 1, 4)]
    assert time_weighted_mean(times, [0.0, 1.0, 5.0]) == pytest.approx(0.75)
    end = datetime(2026, 9, 1, 8, tzinfo=UTC)
    assert time_weighted_mean(times, [0.0, 1.0, 5.0], end) == pytest.approx((3 + 20) / 8)


def _thesis(at, instrument="A", stance="long", resolved=None, **extra):
    return {
        "instrument_id": instrument,
        "stance": stance,
        "started_at": at,
        "resolved_at": resolved,
        **extra,
    }


def test_first_theses_drop_restatements_of_an_open_thesis():
    rows = [
        _thesis("2026-09-01T00:00:00Z", resolved="2026-09-02T00:00:00Z"),
        _thesis("2026-09-01T06:00:00Z", resolved="2026-09-02T00:00:00Z"),  # restated while open
        _thesis("2026-09-03T00:00:00Z", resolved=None),  # a new thesis after the first resolved
        _thesis("2026-09-04T00:00:00Z", resolved=None),  # restated, still open
        _thesis("2026-09-01T00:00:00Z", instrument="B", stance="flat"),  # rejected idea
        _thesis("2026-09-01T00:00:00Z", instrument="B", stance="short"),
    ]
    kept = first_theses(rows)
    assert [(r["instrument_id"], r["started_at"][:10]) for r in kept] == [
        ("A", "2026-09-01"),
        ("B", "2026-09-01"),
        ("A", "2026-09-03"),
    ]


def test_first_market_forecasts_need_a_settlement_probability_and_a_price():
    rows = [
        _thesis(
            "2026-08-30T00:00:00Z",
            "polymarket:1:YES",
            p=0.56,
            p_source="confidence",
            market_price=0.3,
        ),
        _thesis(
            "2026-09-01T00:00:00Z", "polymarket:1:YES", p=0.40, p_source="p_win", market_price=0.3
        ),
        _thesis(
            "2026-09-02T00:00:00Z", "polymarket:1:YES", p=0.70, p_source="p_win", market_price=0.5
        ),
        _thesis(
            "2026-09-01T00:00:00Z", "polymarket:2:NO", p=0.50, p_source="p_win", market_price=None
        ),
        _thesis(
            "2026-09-01T00:00:00Z",
            "polymarket:3:NO",
            "exit",
            p=0.9,
            p_source="p_win",
            market_price=0.8,
        ),
    ]
    kept = first_market_forecasts(rows)
    assert [(r["instrument_id"], r["p"]) for r in kept] == [("polymarket:1:YES", 0.40)]


def test_resolved_outcome_reads_the_token_that_was_held():
    public = {
        "polymarket": {
            "7": {
                "closed": True,
                "uma_resolution_status": "resolved",
                "outcome_prices": {"YES": 0.0, "NO": 1.0},
            },
            "8": {
                "closed": True,
                "uma_resolution_status": "proposed",
                "outcome_prices": {"YES": 1.0, "NO": 0.0},
            },
            "9": {
                "closed": False,
                "uma_resolution_status": None,
                "outcome_prices": {"YES": 0.4, "NO": 0.6},
            },
        }
    }
    assert resolved_outcome("polymarket:7:YES", public) == 0.0
    assert resolved_outcome("polymarket:7:NO", public) == 1.0
    assert resolved_outcome("polymarket:8:YES", public) is None
    assert resolved_outcome("polymarket:9:YES", public) is None
    assert resolved_outcome("kalshi:FED-26SEP:YES", public) is None


def test_us_close_time_follows_new_york_daylight_saving():
    assert _close_time("2026-09-01") == datetime(2026, 9, 1, 20, tzinfo=UTC)
    assert _close_time("2026-12-01") == datetime(2026, 12, 1, 21, tzinfo=UTC)


def test_extract_reads_a_ledger_without_changing_it(tmp_path: Path):
    packet = json.loads((ROOT / "examples/fund-cycle.starting.example.json").read_text())
    decision = FundDecision.model_validate(packet["decision"])
    quotes = [FundQuote.model_validate(item) for item in packet["quotes"]]
    path = tmp_path / "fund.db"
    with PaperFundLedger(path) as ledger:
        ledger.initialize(decision.fund_id, FundMandate())
        ledger.execute_cycle(
            decision,
            quotes,
            runtime=CycleRuntimeMetadata(
                edgecraft_version="test", mandate_digest="test", model="m"
            ),
        )
    before = path.read_bytes()

    extract = extract_ledger(path)

    assert path.read_bytes() == before
    fund = extract["funds"][decision.fund_id]
    assert fund["verification"]["ok"]
    assert len(fund["cycles"]) == 1
    assert fund["risk_checks"]["failed"] == 0
    assert {t["instrument_id"] for t in fund["theses"]} == {
        "SPY",
        "BTC-USD",
        "polymarket:example:YES",
    }
    text = json.dumps(extract)
    assert "source_url" not in text and "thesis" not in text  # numbers only, no research text

    results = build_results(extract, {"polymarket": {}, "spy_daily": []})
    era = results["funds"]["other"]
    assert era["equity"]["start_nav"] == 1000
    assert era["equity"]["spy"] is None
    assert era["trades"]["fills"] == len(fund["fills"])
