from __future__ import annotations

from math import sqrt
from typing import Any

import pandas as pd

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


def _period_return(close: pd.Series, sessions: int) -> float | None:
    if len(close) <= sessions:
        return None
    return float(close.iloc[-1] / close.iloc[-sessions - 1] - 1)
