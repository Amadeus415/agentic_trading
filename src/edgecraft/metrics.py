from __future__ import annotations

from math import e, log, sqrt

import numpy as np
import pandas as pd
from scipy.stats import kurtosis, norm, skew

TRADING_DAYS = 252


def calculate_metrics(
    daily: pd.DataFrame,
    *,
    initial_capital: float,
    turnover_notional: float,
    fills: int,
) -> dict[str, float | int | None]:
    if daily.empty:
        return {}
    returns = daily["return"].dropna()
    years = max((daily.index[-1] - daily.index[0]).days / 365.25, 1 / 365.25)
    nav = (1 + returns).cumprod()
    annual_return = float(nav.iloc[-1] ** (1 / years) - 1) if nav.iloc[-1] > 0 else -1.0
    annual_vol = float(returns.std(ddof=1) * sqrt(TRADING_DAYS)) if len(returns) > 1 else 0.0
    downside = returns.clip(upper=0).std(ddof=1) * sqrt(TRADING_DAYS)
    sharpe = annual_return / annual_vol if annual_vol > 0 else None
    sortino = annual_return / downside if downside and downside > 0 else None
    drawdown = nav / nav.cummax() - 1
    max_drawdown = float(drawdown.min())
    total_contributed = initial_capital + float(daily["contribution"].sum())
    ending_equity = float(daily["equity"].iloc[-1])
    money_gain = ending_equity - total_contributed
    avg_equity = float(daily["equity"].mean())
    exposure = float(daily["gross_exposure"].mean())
    metrics: dict[str, float | int | None] = {
        "ending_equity": ending_equity,
        "net_gain": money_gain,
        "return_on_contributions": money_gain / total_contributed if total_contributed else None,
        "annual_return": annual_return,
        "annual_volatility": annual_vol,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_drawdown": max_drawdown,
        "calmar": annual_return / abs(max_drawdown) if max_drawdown < 0 else None,
        "turnover": turnover_notional / avg_equity if avg_equity else 0,
        "average_exposure": exposure,
        "cash_drag": float((daily["cash"] / daily["equity"].replace(0, np.nan)).mean()),
        "fills": fills,
        "positive_day_rate": float((returns > 0).mean()),
    }
    return {key: _finite(value) for key, value in metrics.items()}


def _finite(value: float | int | None) -> float | int | None:
    if value is None or isinstance(value, int):
        return value
    return float(value) if np.isfinite(value) else None


def deflated_sharpe_ratio(
    returns: pd.Series, observed_sharpe: float | None, trials: int
) -> float | None:
    """Bailey–López de Prado DSR with non-normal return correction."""
    values = returns.dropna().to_numpy(dtype=float)
    if observed_sharpe is None or len(values) < 30 or trials < 1:
        return None
    trials = max(1, trials)
    euler_gamma = 0.5772156649
    expected_max = (
        (1 - euler_gamma) * norm.ppf(1 - 1 / trials) + euler_gamma * norm.ppf(1 - 1 / (trials * e))
        if trials > 1
        else 0.0
    )
    denominator = sqrt(
        max(
            1e-12,
            (
                1
                - skew(values, bias=False) * observed_sharpe
                + ((kurtosis(values, fisher=False, bias=False) - 1) / 4) * observed_sharpe**2
            )
            / (len(values) - 1),
        )
    )
    return float(norm.cdf((observed_sharpe - expected_max) / denominator))


def block_bootstrap_interval(
    returns: pd.Series,
    *,
    samples: int,
    block_size: int,
    seed: int,
) -> dict[str, float | None]:
    values = returns.dropna().to_numpy(dtype=float)
    if samples <= 0 or len(values) < max(30, block_size * 2):
        return {
            "annual_return_low": None,
            "annual_return_high": None,
            "sharpe_low": None,
            "sharpe_high": None,
        }
    rng = np.random.default_rng(seed)
    ann: list[float] = []
    sharpes: list[float] = []
    for _ in range(samples):
        chunks: list[np.ndarray] = []
        while sum(len(chunk) for chunk in chunks) < len(values):
            start = int(rng.integers(0, len(values) - block_size + 1))
            chunks.append(values[start : start + block_size])
        sample = np.concatenate(chunks)[: len(values)]
        annual_return = float(np.prod(1 + sample) ** (TRADING_DAYS / len(sample)) - 1)
        annual_vol = float(np.std(sample, ddof=1) * sqrt(TRADING_DAYS))
        ann.append(annual_return)
        sharpes.append(annual_return / annual_vol if annual_vol > 0 else 0.0)
    return {
        "annual_return_low": float(np.quantile(ann, 0.025)),
        "annual_return_high": float(np.quantile(ann, 0.975)),
        "sharpe_low": float(np.quantile(sharpes, 0.025)),
        "sharpe_high": float(np.quantile(sharpes, 0.975)),
    }


def probability_backtest_overfitting(return_matrix: pd.DataFrame, slices: int = 8) -> float | None:
    """CSCV estimate: fraction of selected in-sample winners below median out-of-sample."""
    clean = return_matrix.dropna(how="any")
    if clean.shape[1] < 2 or len(clean) < slices * 10 or slices % 2:
        return None
    chunks = np.array_split(np.arange(len(clean)), slices)
    from itertools import combinations

    logits: list[float] = []
    for train_ids in combinations(range(slices), slices // 2):
        test_ids = [index for index in range(slices) if index not in train_ids]
        train_rows = np.concatenate([chunks[index] for index in train_ids])
        test_rows = np.concatenate([chunks[index] for index in test_ids])
        train = _sharpe_columns(clean.iloc[train_rows])
        test = _sharpe_columns(clean.iloc[test_rows])
        winner = train.idxmax()
        rank = float(test.rank(method="average")[winner])
        relative_rank = min(max((rank - 0.5) / len(test), 1e-6), 1 - 1e-6)
        logits.append(log(relative_rank / (1 - relative_rank)))
    return float(np.mean(np.asarray(logits) <= 0)) if logits else None


def _sharpe_columns(frame: pd.DataFrame) -> pd.Series:
    annual = (1 + frame).prod() ** (TRADING_DAYS / len(frame)) - 1
    vol = frame.std(ddof=1) * sqrt(TRADING_DAYS)
    return annual / vol.replace(0, np.nan)
