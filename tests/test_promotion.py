from edgecraft.promotion import build_research_evidence


def _backtest(candidate_gain: float, baseline_gain: float, *, pbo: float = 0.2):
    return {
        "meta": {"end": "2026-07-18"},
        "validation": {"probability_backtest_overfitting": pbo},
        "results": [
            {
                "strategy": "plain_dca",
                "metrics": {
                    "return_on_contributions": baseline_gain,
                    "deflated_sharpe_probability": 0.99,
                },
            },
            {
                "strategy": "candidate",
                "metrics": {
                    "return_on_contributions": candidate_gain,
                    "deflated_sharpe_probability": 0.99,
                },
            },
        ],
    }


def test_promotion_evidence_is_derived_and_content_addressed():
    backtest = _backtest(0.3, 0.2)
    walk = {
        "summary": {"passed": True},
        "folds": [{"selected_strategy": "candidate"}, {"selected_strategy": "candidate"}],
    }
    stress = _backtest(0.25, 0.2)

    first = build_research_evidence(backtest, walk, stress, strategy="candidate")
    second = build_research_evidence(backtest, walk, stress, strategy="candidate")

    assert first.experiment_id == second.experiment_id
    assert first.walk_forward_passed
    assert first.benchmark_beaten
    assert first.cost_stress_passed
    assert first.multiple_testing_passed
