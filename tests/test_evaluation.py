from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from edgecraft.autonomy_models import Mandate
from edgecraft.evaluation import advance_evaluation, evaluation_report
from edgecraft.execution_models import MarketQuote, TradeProposal

NOW = datetime(2026, 7, 20, 15, 0, tzinfo=UTC)


def _mandate() -> Mandate:
    return Mandate(
        mandate_id="evaluation_test",
        goal="Evaluate agent decisions against cash-flow-matched passive sleeves.",
        weekly_budget="10",
        universe=["AAA", "BBB"],
        strategic_weights={"AAA": "0.6", "BBB": "0.4"},
        benchmark="SPY",
        evaluation_cost_bps="0",
        policy_path="unused.json",
    )


def _proposal(*, invest: bool) -> TradeProposal:
    orders = (
        [
            {
                "order_key": "agent-aaa",
                "symbol": "AAA",
                "side": "buy",
                "notional": 10,
                "expected_price": 100,
                "rationale": "Test the candidate sleeve allocation.",
                "quote_as_of": NOW,
            }
        ]
        if invest
        else []
    )
    return TradeProposal.model_validate(
        {
            "proposal_id": f"proposal-{'invest' if invest else 'hold'}",
            "mandate_id": "evaluation_test",
            "run_id": f"run-{'invest' if invest else 'hold'}",
            "created_at": NOW,
            "mode": "shadow",
            "account_id": "test",
            "strategy": "agentic_weekly_dca",
            "rationale": "Evaluate one frozen decision.",
            "policy_name": "test",
            "snapshot_as_of": NOW,
            "orders": orders,
            "risk": {
                "approved_for_review": invest,
                "projected_cash": 0 if invest else 10,
                "projected_weights": {"AAA": 1} if invest else {},
                "gross_notional": 10 if invest else 0,
                "violations": [] if invest else ["reasoning agent elected to hold this cycle"],
            },
            "robinhood_handoff": {},
        }
    )


def _quotes(aaa: float, bbb: float, spy: float, *, at: datetime) -> list[MarketQuote]:
    return [
        MarketQuote(symbol=symbol, last=price, as_of=at)
        for symbol, price in (("AAA", aaa), ("BBB", bbb), ("SPY", spy))
    ]


def test_cash_flow_matched_evaluation_tracks_agent_benchmark_and_strategic_sleeves():
    mandate = _mandate()
    state, first = advance_evaluation(
        mandate,
        _proposal(invest=True),
        _quotes(100, 100, 100, at=NOW),
        run_id="run-invest",
        cycle_key="evaluation_test:2026-W30",
        observed_at=NOW,
        prior=None,
        cost_bps=mandate.evaluation_cost_bps,
    )
    later = NOW + timedelta(days=7)
    state, second = advance_evaluation(
        mandate,
        _proposal(invest=False),
        _quotes(110, 100, 105, at=later),
        run_id="run-hold",
        cycle_key="evaluation_test:2026-W31",
        observed_at=later,
        prior=state,
        cost_bps=mandate.evaluation_cost_bps,
    )

    report = evaluation_report(state, [first, second])

    assert report["observation_count"] == 2
    assert report["invest_decisions"] == 1
    assert report["hold_decisions"] == 1
    assert report["sleeves"]["agent"]["value"] == pytest.approx(21)
    assert report["sleeves"]["benchmark"]["value"] == pytest.approx(20.5)
    assert report["sleeves"]["strategic"]["value"] == pytest.approx(20.6)
    assert report["sleeves"]["agent"]["time_weighted_return"] == pytest.approx(0.10)
    assert report["sleeves"]["benchmark"]["time_weighted_return"] == pytest.approx(0.05)
    assert report["agent_excess_return_on_contributions"] == pytest.approx(0.025)


def test_evaluation_requires_complete_point_in_time_prices():
    with pytest.raises(ValueError, match="missing quotes"):
        advance_evaluation(
            _mandate(),
            _proposal(invest=True),
            _quotes(100, 100, 100, at=NOW)[:-1],
            run_id="run-invest",
            cycle_key="evaluation_test:2026-W30",
            observed_at=NOW,
            prior=None,
        )


def test_evaluation_uses_completed_session_prices_for_unrelated_symbols():
    state, observation = advance_evaluation(
        _mandate(),
        _proposal(invest=True),
        [MarketQuote(symbol="AAA", last=100, as_of=NOW)],
        completed_session_prices={"BBB": 90, "SPY": 110},
        run_id="run-invest",
        cycle_key="evaluation_test:2026-W30",
        observed_at=NOW,
        prior=None,
        cost_bps=Decimal("0"),
    )

    assert state.agent.positions["AAA"] == Decimal("0.1")
    assert observation.prices == {
        "AAA": Decimal("100"),
        "BBB": Decimal("90"),
        "SPY": Decimal("110"),
    }
