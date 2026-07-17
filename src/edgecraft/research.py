from __future__ import annotations

from dataclasses import asdict
from typing import Any

import pandas as pd

from edgecraft.engine import BacktestEngine
from edgecraft.metrics import (
    block_bootstrap_interval,
    deflated_sharpe_ratio,
    probability_backtest_overfitting,
)
from edgecraft.models import BacktestRequest, BacktestResult
from edgecraft.strategies import build_strategy


def run_research(data: dict[str, pd.DataFrame], request: BacktestRequest) -> dict[str, Any]:
    engine = BacktestEngine(request.costs)
    results: list[BacktestResult] = []
    used_names: dict[str, int] = {}
    for spec in request.strategies:
        strategy = build_strategy(spec.name, spec.params)
        result = engine.run(
            data,
            strategy,
            initial_capital=request.initial_capital,
            contribution_amount=request.contribution_amount,
            contribution_frequency=request.contribution_frequency,
        )
        used_names[spec.name] = used_names.get(spec.name, 0) + 1
        suffix = used_names[spec.name]
        result.strategy = spec.name if suffix == 1 else f"{spec.name}_{suffix}"
        results.append(result)

    return_matrix = pd.concat(
        {result.strategy: result.daily["return"] for result in results}, axis=1
    ).dropna(how="all")
    pbo = probability_backtest_overfitting(return_matrix, request.validation.cscv_slices)
    trials = len(results)
    payload_results = []
    for index, result in enumerate(results):
        result.metrics["deflated_sharpe_probability"] = deflated_sharpe_ratio(
            result.daily["return"], result.metrics.get("sharpe"), trials
        )
        bootstrap = block_bootstrap_interval(
            result.daily["return"],
            samples=request.validation.bootstrap_samples,
            block_size=request.validation.bootstrap_block_size,
            seed=request.validation.random_seed + index,
        )
        result.metrics.update(bootstrap)
        payload_results.append(serialize_result(result))

    return {
        "meta": {
            "symbols": request.symbols,
            "start": str(return_matrix.index.min().date()),
            "end": str(return_matrix.index.max().date()),
            "sessions": len(return_matrix),
            "strategies_tested": len(results),
            "execution": "close signal → next session adjusted open",
        },
        "validation": {
            "probability_backtest_overfitting": pbo,
            "cscv_slices": request.validation.cscv_slices,
            "bootstrap_samples": request.validation.bootstrap_samples,
            "bootstrap_block_size": request.validation.bootstrap_block_size,
        },
        "results": payload_results,
    }


def serialize_result(result: BacktestResult) -> dict[str, Any]:
    sampled = result.daily.iloc[:: max(1, len(result.daily) // 900)].copy()
    if sampled.index[-1] != result.daily.index[-1]:
        sampled = pd.concat([sampled, result.daily.iloc[[-1]]])
    series = [
        {
            "date": str(date.date()),
            "equity": round(float(row.equity), 2),
            "drawdown": round(float(row.drawdown), 6),
            "cash": round(float(row.cash), 2),
        }
        for date, row in sampled.iterrows()
    ]
    return {
        "strategy": result.strategy,
        "params": result.params,
        "metrics": result.metrics,
        "series": series,
        "fills": [
            {
                **asdict(fill),
                "date": str(fill.date.date()),
                "quantity": round(fill.quantity, 6),
                "price": round(fill.price, 4),
                "notional": round(fill.notional, 2),
                "costs": round(fill.costs, 2),
            }
            for fill in result.fills[-500:]
        ],
    }
