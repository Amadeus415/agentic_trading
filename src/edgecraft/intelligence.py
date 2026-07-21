from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from math import sqrt
from pathlib import Path
from typing import Protocol

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field, field_validator

from edgecraft.data import MarketDataProvider
from edgecraft.indicators import rsi


class AssetIntelligence(BaseModel):
    symbol: str
    last_close: float = Field(gt=0)
    return_1d: float | None
    return_5d: float | None
    return_20d: float | None
    return_63d: float | None
    return_126d: float | None
    realized_volatility_20d: float | None = Field(default=None, ge=0)
    realized_volatility_63d: float | None = Field(default=None, ge=0)
    downside_volatility_63d: float | None = Field(default=None, ge=0)
    drawdown_252d: float | None
    rsi_14: float | None
    distance_from_sma_50: float | None
    distance_from_sma_200: float | None
    beta_252d: float | None
    correlation_to_benchmark_252d: float | None
    average_daily_dollar_volume_20d: float = Field(gt=0)
    cross_sectional_score: float
    cross_sectional_rank: int = Field(ge=1)


class MarketRegime(BaseModel):
    benchmark_above_sma_200: bool
    benchmark_return_20d: float | None
    benchmark_realized_volatility_20d: float | None
    universe_breadth_above_sma_50: float = Field(ge=0, le=1)
    cross_sectional_return_dispersion_20d: float = Field(ge=0)


class MarketIntelligenceSnapshot(BaseModel):
    schema_version: str = "edgecraft.market-intelligence.v1"
    collected_at: datetime
    last_completed_session: date
    provider: str = "yahoo_adjusted_daily"
    benchmark: str
    symbols: list[str]
    history_sessions: int = Field(ge=60)
    input_sha256: str = Field(min_length=64, max_length=64)
    regime: MarketRegime
    assets: dict[str, AssetIntelligence]
    warnings: list[str] = Field(default_factory=list)

    @field_validator("collected_at")
    @classmethod
    def aware_collected_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("market intelligence collected_at must include a timezone")
        return value.astimezone(UTC)


class MarketIntelligenceCollector(Protocol):
    def collect(
        self,
        symbols: list[str],
        *,
        benchmark: str,
        now: datetime | None = None,
    ) -> MarketIntelligenceSnapshot: ...


class YahooMarketIntelligenceCollector:
    def __init__(
        self,
        *,
        data_provider: MarketDataProvider | None = None,
        lookback_days: int = 1_100,
    ) -> None:
        self.data_provider = data_provider or MarketDataProvider()
        self.lookback_days = lookback_days

    def collect(
        self,
        symbols: list[str],
        *,
        benchmark: str,
        now: datetime | None = None,
    ) -> MarketIntelligenceSnapshot:
        current = (now or datetime.now(UTC)).astimezone(UTC)
        clean_benchmark = benchmark.strip().upper()
        clean_symbols = list(
            dict.fromkeys([*(symbol.strip().upper() for symbol in symbols), clean_benchmark])
        )
        end = current.date()
        start = end - timedelta(days=self.lookback_days)
        data = self.data_provider.load(
            clean_symbols,
            start.isoformat(),
            end.isoformat(),
        )
        return build_market_intelligence(
            data,
            benchmark=clean_benchmark,
            collected_at=current,
        )


def build_market_intelligence(
    data: dict[str, pd.DataFrame],
    *,
    benchmark: str,
    collected_at: datetime,
) -> MarketIntelligenceSnapshot:
    if benchmark not in data:
        raise ValueError(f"benchmark {benchmark} is missing from market intelligence data")
    closes = pd.DataFrame({symbol: frame["close"] for symbol, frame in data.items()}).dropna()
    volumes = pd.DataFrame({symbol: frame["volume"] for symbol, frame in data.items()}).loc[
        closes.index
    ]
    if len(closes) < 252:
        raise ValueError("market intelligence requires at least 252 common sessions")
    returns = closes.pct_change(fill_method=None)
    benchmark_returns = returns[benchmark]
    raw_features: dict[str, dict[str, float | None]] = {}
    for symbol in closes:
        close = closes[symbol]
        asset_returns = returns[symbol]
        downside = asset_returns.iloc[-63:]
        downside = downside[downside < 0]
        benchmark_variance = float(benchmark_returns.iloc[-252:].var(ddof=1))
        raw_features[symbol] = {
            "return_1d": _period_return(close, 1),
            "return_5d": _period_return(close, 5),
            "return_20d": _period_return(close, 20),
            "return_63d": _period_return(close, 63),
            "return_126d": _period_return(close, 126),
            "realized_volatility_20d": _annualized_vol(asset_returns, 20),
            "realized_volatility_63d": _annualized_vol(asset_returns, 63),
            "downside_volatility_63d": (
                float(downside.std(ddof=1) * sqrt(252)) if len(downside) >= 2 else None
            ),
            "drawdown_252d": float(close.iloc[-1] / close.iloc[-252:].max() - 1),
            "rsi_14": float(rsi(close, 14).iloc[-1]),
            "distance_from_sma_50": float(close.iloc[-1] / close.iloc[-50:].mean() - 1),
            "distance_from_sma_200": float(close.iloc[-1] / close.iloc[-200:].mean() - 1),
            "beta_252d": (
                float(
                    asset_returns.iloc[-252:].cov(benchmark_returns.iloc[-252:])
                    / benchmark_variance
                )
                if benchmark_variance > 0
                else None
            ),
            "correlation_to_benchmark_252d": float(
                asset_returns.iloc[-252:].corr(benchmark_returns.iloc[-252:])
            ),
        }

    score_symbols = [symbol for symbol in closes if symbol != benchmark] or [benchmark]
    momentum_20 = np.array([raw_features[symbol]["return_20d"] for symbol in score_symbols])
    momentum_63 = np.array([raw_features[symbol]["return_63d"] for symbol in score_symbols])
    volatility = np.array(
        [raw_features[symbol]["realized_volatility_63d"] for symbol in score_symbols]
    )
    scores = _zscore(momentum_63) + 0.5 * _zscore(momentum_20) - 0.5 * _zscore(volatility)
    score_map = {symbol: float(score) for symbol, score in zip(score_symbols, scores, strict=True)}
    ranked = sorted(score_symbols, key=lambda symbol: (-score_map[symbol], symbol))
    rank_map = {symbol: index + 1 for index, symbol in enumerate(ranked)}
    if benchmark not in score_map:
        # The benchmark supplies regime and factor context; it must never
        # displace an eligible mandate asset in the cross-sectional ranking.
        score_map[benchmark] = 0.0
        rank_map[benchmark] = len(score_symbols) + 1
    assets = {
        symbol: AssetIntelligence(
            symbol=symbol,
            last_close=float(closes[symbol].iloc[-1]),
            average_daily_dollar_volume_20d=float(
                (closes[symbol].iloc[-20:] * volumes[symbol].iloc[-20:]).mean()
            ),
            cross_sectional_score=score_map[symbol],
            cross_sectional_rank=rank_map[symbol],
            **raw_features[symbol],
        )
        for symbol in closes
    }
    benchmark_close = closes[benchmark]
    breadth = float(
        np.mean(
            [bool(closes[symbol].iloc[-1] > closes[symbol].iloc[-50:].mean()) for symbol in closes]
        )
    )
    digest_input = {
        symbol: {
            "last_date": str(closes.index[-1].date()),
            "last_close": float(closes[symbol].iloc[-1]),
            "last_volume": float(volumes[symbol].iloc[-1]),
            "sessions": len(closes),
        }
        for symbol in sorted(closes)
    }
    digest = hashlib.sha256(
        json.dumps(digest_input, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return MarketIntelligenceSnapshot(
        collected_at=collected_at,
        last_completed_session=closes.index[-1].date(),
        benchmark=benchmark,
        symbols=list(closes.columns),
        history_sessions=len(closes),
        input_sha256=digest,
        regime=MarketRegime(
            benchmark_above_sma_200=bool(
                benchmark_close.iloc[-1] > benchmark_close.iloc[-200:].mean()
            ),
            benchmark_return_20d=_period_return(benchmark_close, 20),
            benchmark_realized_volatility_20d=_annualized_vol(benchmark_returns, 20),
            universe_breadth_above_sma_50=breadth,
            cross_sectional_return_dispersion_20d=float(
                np.std(
                    [raw_features[symbol]["return_20d"] for symbol in score_symbols],
                    ddof=1 if len(score_symbols) > 1 else 0,
                )
            ),
        ),
        assets=assets,
    )


def write_market_intelligence(snapshot: MarketIntelligenceSnapshot, path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    target.write_text(snapshot.model_dump_json(indent=2) + "\n", encoding="utf-8")
    target.chmod(0o600)
    return target


def _period_return(close: pd.Series, sessions: int) -> float | None:
    if len(close) <= sessions:
        return None
    return float(close.iloc[-1] / close.iloc[-sessions - 1] - 1)


def _annualized_vol(returns: pd.Series, sessions: int) -> float | None:
    sample = returns.iloc[-sessions:].dropna()
    return float(sample.std(ddof=1) * sqrt(252)) if len(sample) >= 2 else None


def _zscore(values: np.ndarray) -> np.ndarray:
    values = values.astype(float)
    standard_deviation = float(np.std(values))
    if standard_deviation <= 1e-12:
        return np.zeros_like(values)
    return (values - float(np.mean(values))) / standard_deviation
