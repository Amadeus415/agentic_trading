from __future__ import annotations

import numpy as np
import pandas as pd


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = -delta.clip(upper=0).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)


def realized_volatility(close: pd.Series, window: int = 20) -> pd.Series:
    return close.pct_change().rolling(window).std(ddof=1) * np.sqrt(252)


def feature_frame(frame: pd.DataFrame) -> pd.DataFrame:
    close = frame["close"]
    returns = close.pct_change()
    true_range = pd.concat(
        [
            frame["high"] - frame["low"],
            (frame["high"] - close.shift()).abs(),
            (frame["low"] - close.shift()).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return pd.DataFrame(
        {
            "ret_1": returns,
            "ret_5": close.pct_change(5),
            "ret_20": close.pct_change(20),
            "momentum_63": close.pct_change(63),
            "vol_20": returns.rolling(20).std(ddof=1) * np.sqrt(252),
            "sma_ratio": close.rolling(20).mean() / close.rolling(100).mean() - 1,
            "rsi_14": rsi(close, 14) / 100,
            "drawdown_63": close / close.rolling(63).max() - 1,
            "atr_14": true_range.rolling(14).mean() / close,
            "volume_z": (
                (frame["volume"] - frame["volume"].rolling(20).mean())
                / frame["volume"].rolling(20).std(ddof=1)
            ),
        }
    ).replace([np.inf, -np.inf], np.nan)
