from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from edgecraft.execution_models import ResearchEvidence


def build_research_evidence(
    backtest: dict[str, Any],
    walk_forward: dict[str, Any],
    cost_stress: dict[str, Any],
    *,
    strategy: str,
    benchmark: str = "plain_dca",
) -> ResearchEvidence:
    candidate = _result(backtest, strategy)
    baseline = _result(backtest, benchmark)
    stressed_candidate = _result(cost_stress, strategy)
    stressed_baseline = _result(cost_stress, benchmark)
    selected = {fold["selected_strategy"] for fold in walk_forward.get("folds", [])}
    walk_passed = bool(walk_forward.get("summary", {}).get("passed")) and selected == {strategy}
    benchmark_beaten = _gain(candidate) > _gain(baseline)
    cost_stress_passed = _gain(stressed_candidate) > _gain(stressed_baseline)
    pbo = backtest.get("validation", {}).get("probability_backtest_overfitting")
    dsr = candidate.get("metrics", {}).get("deflated_sharpe_probability")
    multiple_testing_passed = (
        pbo is not None and float(pbo) <= 0.5 and dsr is not None and float(dsr) >= 0.95
    )
    identity = json.dumps(
        {
            "backtest": backtest,
            "walk_forward": walk_forward,
            "cost_stress": cost_stress,
            "strategy": strategy,
            "benchmark": benchmark,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    experiment_id = "exp_" + hashlib.sha256(identity.encode()).hexdigest()[:24]
    data_end = datetime.fromisoformat(backtest["meta"]["end"]).replace(tzinfo=UTC)
    return ResearchEvidence(
        experiment_id=experiment_id,
        strategy=strategy,
        benchmark=benchmark,
        data_end=data_end,
        walk_forward_passed=walk_passed,
        benchmark_beaten=benchmark_beaten,
        cost_stress_passed=cost_stress_passed,
        multiple_testing_passed=multiple_testing_passed,
        notes=[
            f"walk_forward_selected={sorted(selected)}",
            f"candidate_gain={_gain(candidate):.8f}",
            f"benchmark_gain={_gain(baseline):.8f}",
            f"stressed_candidate_gain={_gain(stressed_candidate):.8f}",
            f"stressed_benchmark_gain={_gain(stressed_baseline):.8f}",
            f"pbo={pbo}",
            f"deflated_sharpe_probability={dsr}",
        ],
    )


def _result(payload: dict[str, Any], strategy: str) -> dict[str, Any]:
    for result in payload.get("results", []):
        if result.get("strategy") == strategy:
            return result
    raise ValueError(f"artifact does not contain strategy: {strategy}")


def _gain(result: dict[str, Any]) -> float:
    value = result.get("metrics", {}).get("return_on_contributions")
    if value is None:
        raise ValueError(f"strategy {result.get('strategy')} has no return_on_contributions")
    return float(value)
