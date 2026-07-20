from __future__ import annotations

from math import sqrt
from typing import Any

import numpy as np
import pandas as pd

from edgecraft.execution_models import PortfolioSnapshot
from edgecraft.indicators import rsi


def market_diagnostics(
    data: dict[str, pd.DataFrame], *, benchmark: str | None = None
) -> dict[str, Any]:
    closes = pd.DataFrame({symbol: frame["close"] for symbol, frame in data.items()})
    returns = closes.pct_change().dropna()
    benchmark = benchmark or next(iter(data))
    if benchmark not in data:
        raise ValueError(f"benchmark {benchmark} is not in the loaded universe")
    benchmark_returns = returns[benchmark]
    assets: dict[str, Any] = {}
    for symbol, close in closes.items():
        asset_returns = returns[symbol]
        recent_asset = asset_returns.iloc[-252:]
        recent_benchmark = benchmark_returns.iloc[-252:]
        variance = float(recent_benchmark.var(ddof=1))
        beta = float(recent_asset.cov(recent_benchmark) / variance) if variance > 0 else None
        assets[symbol] = {
            "last_close": float(close.iloc[-1]),
            "return_1d": _period_return(close, 1),
            "return_5d": _period_return(close, 5),
            "return_20d": _period_return(close, 20),
            "return_63d": _period_return(close, 63),
            "realized_volatility_20d": float(asset_returns.iloc[-20:].std(ddof=1) * sqrt(252)),
            "drawdown_252d": float(close.iloc[-1] / close.iloc[-252:].max() - 1),
            "rsi_14": float(rsi(close, 14).iloc[-1]),
            "above_sma_50": bool(close.iloc[-1] > close.iloc[-50:].mean()),
            "above_sma_200": bool(close.iloc[-1] > close.iloc[-200:].mean()),
            "beta_252d": beta,
            "correlation_to_benchmark_252d": float(
                asset_returns.iloc[-252:].corr(benchmark_returns.iloc[-252:])
            ),
        }
    return {
        "schema_version": "edgecraft.market-diagnostics.v1",
        "as_of": str(closes.index[-1].date()),
        "sessions": len(closes),
        "benchmark": benchmark,
        "assets": assets,
        "correlations_252d": returns.iloc[-252:].corr().to_dict(),
    }


def portfolio_market_risk(
    snapshot: PortfolioSnapshot,
    data: dict[str, pd.DataFrame],
    *,
    benchmark: str = "SPY",
) -> dict[str, Any]:
    held = [position.symbol for position in snapshot.positions if position.market_value > 0]
    if not held:
        raise ValueError("portfolio has no invested equity positions")
    missing = set(held + [benchmark]) - set(data)
    if missing:
        raise ValueError(f"missing market history for: {sorted(missing)}")
    returns = pd.DataFrame(
        {symbol: data[symbol]["close"].pct_change() for symbol in set(held + [benchmark])}
    ).dropna()
    weights = np.array(
        [
            next(
                position.market_value
                for position in snapshot.positions
                if position.symbol == symbol
            )
            / snapshot.portfolio_value
            for symbol in held
        ],
        dtype=float,
    )
    asset_returns = returns[held]
    portfolio_returns = asset_returns.to_numpy() @ weights
    covariance = asset_returns.cov().to_numpy() * 252
    variance = float(weights @ covariance @ weights)
    annual_volatility = sqrt(max(0.0, variance))
    benchmark_returns = returns[benchmark].to_numpy()
    benchmark_variance = float(np.var(benchmark_returns, ddof=1))
    beta = (
        float(np.cov(portfolio_returns, benchmark_returns, ddof=1)[0, 1] / benchmark_variance)
        if benchmark_variance > 0
        else None
    )
    quantile = float(np.quantile(portfolio_returns, 0.05))
    tail = portfolio_returns[portfolio_returns <= quantile]
    compounded = np.cumprod(1 + portfolio_returns)
    drawdown = compounded / np.maximum.accumulate(compounded) - 1
    component_risk: dict[str, float | None] = {}
    if variance > 0:
        contributions = weights * (covariance @ weights) / variance
        component_risk = {
            symbol: float(contribution)
            for symbol, contribution in zip(held, contributions, strict=True)
        }
    else:
        component_risk = {symbol: None for symbol in held}
    return {
        "schema_version": "edgecraft.portfolio-risk.v1",
        "as_of": str(returns.index[-1].date()),
        "sessions": len(returns),
        "benchmark": benchmark,
        "invested_weight": float(weights.sum()),
        "cash_weight": snapshot.buying_power / snapshot.portfolio_value,
        "annualized_volatility": annual_volatility,
        "beta": beta,
        "historical_var_95_one_day": max(0.0, -quantile),
        "historical_expected_shortfall_95_one_day": (
            max(0.0, -float(tail.mean())) if len(tail) else None
        ),
        "worst_day": float(np.min(portfolio_returns)),
        "max_drawdown": float(np.min(drawdown)),
        "component_variance_share": component_risk,
        "asset_correlations": asset_returns.corr().to_dict(),
    }


def _period_return(close: pd.Series, sessions: int) -> float | None:
    if len(close) <= sessions:
        return None
    return float(close.iloc[-1] / close.iloc[-sessions - 1] - 1)
