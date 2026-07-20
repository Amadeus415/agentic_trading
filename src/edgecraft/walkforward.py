from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from edgecraft.engine import BacktestEngine
from edgecraft.models import BacktestRequest, StrategySpec
from edgecraft.strategies import build_strategy


@dataclass(slots=True)
class _Candidate:
    spec: StrategySpec
    score: float


def walk_forward_validate(
    data: dict[str, pd.DataFrame],
    request: BacktestRequest,
    *,
    train_sessions: int = 504,
    test_sessions: int = 126,
    step_sessions: int | None = None,
    benchmark: str = "plain_dca",
) -> dict[str, Any]:
    """Select on rolling training windows and evaluate only on subsequent sessions."""
    if train_sessions < 60 or test_sessions < 20:
        raise ValueError("train_sessions must be >=60 and test_sessions must be >=20")
    step = step_sessions or test_sessions
    if step < test_sessions:
        raise ValueError("overlapping test windows are not supported")
    dates = data[next(iter(data))].index
    if len(dates) < train_sessions + test_sessions:
        raise ValueError(
            f"need at least {train_sessions + test_sessions} sessions, received {len(dates)}"
        )
    candidates = [spec for spec in request.strategies if spec.name != benchmark]
    if not candidates:
        raise ValueError("walk-forward validation needs a non-benchmark strategy")

    engine = BacktestEngine(request.costs)
    folds: list[dict[str, Any]] = []
    candidate_oos: list[pd.Series] = []
    benchmark_oos: list[pd.Series] = []
    for train_start in range(0, len(dates) - train_sessions - test_sessions + 1, step):
        train_end_index = train_start + train_sessions
        test_end_index = train_end_index + test_sessions
        train_dates = dates[train_start:train_end_index]
        context_dates = dates[train_start:test_end_index]
        test_start = dates[train_end_index]
        train_data = {symbol: frame.loc[train_dates] for symbol, frame in data.items()}
        context_data = {symbol: frame.loc[context_dates] for symbol, frame in data.items()}

        scored: list[_Candidate] = []
        for spec in candidates:
            result = engine.run(
                train_data,
                build_strategy(spec.name, spec.params),
                initial_capital=request.initial_capital,
                contribution_amount=request.contribution_amount,
                contribution_frequency=request.contribution_frequency,
            )
            score = result.metrics.get("sharpe")
            scored.append(_Candidate(spec, float(score) if score is not None else -np.inf))
        winner = max(scored, key=lambda item: item.score)
        selected = engine.run(
            context_data,
            build_strategy(winner.spec.name, winner.spec.params),
            initial_capital=request.initial_capital,
            contribution_amount=request.contribution_amount,
            contribution_frequency=request.contribution_frequency,
            evaluation_start=test_start,
        )
        baseline = engine.run(
            context_data,
            build_strategy(benchmark),
            initial_capital=request.initial_capital,
            contribution_amount=request.contribution_amount,
            contribution_frequency=request.contribution_frequency,
            evaluation_start=test_start,
        )
        candidate_oos.append(selected.daily["return"])
        benchmark_oos.append(baseline.daily["return"])
        selected_return = _compound(selected.daily["return"])
        benchmark_return = _compound(baseline.daily["return"])
        folds.append(
            {
                "fold": len(folds) + 1,
                "train_start": str(train_dates[0].date()),
                "train_end": str(train_dates[-1].date()),
                "test_start": str(test_start.date()),
                "test_end": str(context_dates[-1].date()),
                "selected_strategy": winner.spec.name,
                "training_sharpe": None if not np.isfinite(winner.score) else winner.score,
                "oos_return": selected_return,
                "benchmark_return": benchmark_return,
                "excess_return": selected_return - benchmark_return,
                "oos_max_drawdown": selected.metrics["max_drawdown"],
            }
        )

    candidate_returns = pd.concat(candidate_oos).sort_index()
    baseline_returns = pd.concat(benchmark_oos).sort_index()
    if candidate_returns.index.duplicated().any() or baseline_returns.index.duplicated().any():
        raise ValueError("walk-forward configuration produced overlapping test observations")
    total_candidate = _compound(candidate_returns)
    total_benchmark = _compound(baseline_returns)
    fold_wins = sum(fold["excess_return"] > 0 for fold in folds)
    return {
        "schema_version": "edgecraft.walk-forward.v1",
        "method": {
            "selection_metric": "training Sharpe",
            "execution": "close signal -> next session open",
            "train_sessions": train_sessions,
            "test_sessions": test_sessions,
            "step_sessions": step,
            "benchmark": benchmark,
            "test_windows_overlap": False,
        },
        "summary": {
            "folds": len(folds),
            "oos_sessions": len(candidate_returns),
            "oos_return": total_candidate,
            "benchmark_return": total_benchmark,
            "excess_return": total_candidate - total_benchmark,
            "fold_win_rate": fold_wins / len(folds),
            "passed": len(folds) >= 2
            and total_candidate > total_benchmark
            and fold_wins / len(folds) >= 0.5,
        },
        "folds": folds,
    }


def _compound(returns: pd.Series) -> float:
    return float((1 + returns.fillna(0)).prod() - 1)
