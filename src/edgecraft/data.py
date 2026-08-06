from __future__ import annotations

import hashlib
import time
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

REQUIRED_COLUMNS = ("open", "high", "low", "close", "volume")
DOWNLOAD_RETRY_DELAYS_SECONDS = (0.5, 1.5, 3.0)
DOWNLOAD_TIMEOUT_SECONDS = 20.0


class MarketDataError(RuntimeError):
    pass


class MarketDataProvider:
    """Adjusted daily OHLCV with an on-disk cache and strict validation."""

    def __init__(
        self,
        cache_dir: str | Path = "data/cache",
        *,
        retry_delays_seconds: tuple[float, ...] = DOWNLOAD_RETRY_DELAYS_SECONDS,
        download_timeout: float = DOWNLOAD_TIMEOUT_SECONDS,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.retry_delays_seconds = tuple(retry_delays_seconds)
        self.download_timeout = float(download_timeout)

    def load(
        self, symbols: list[str], start: str, end: str, *, refresh: bool = False
    ) -> dict[str, pd.DataFrame]:
        frames: dict[str, pd.DataFrame] = {}
        errors: list[str] = []
        for symbol in symbols:
            try:
                frames[symbol] = self._load_symbol(symbol, start, end, refresh=refresh)
            except Exception as exc:  # aggregate errors across the requested universe
                errors.append(f"{symbol}: {exc}")
        if errors:
            raise MarketDataError("; ".join(errors))
        common = sorted(set.intersection(*(set(frame.index) for frame in frames.values())))
        if len(common) < 60:
            raise MarketDataError("The requested universe has fewer than 60 common sessions")
        return {symbol: frame.loc[common].copy() for symbol, frame in frames.items()}

    def _load_symbol(self, symbol: str, start: str, end: str, *, refresh: bool) -> pd.DataFrame:
        key = hashlib.sha256(f"v2:{symbol}:{start}:{end}".encode()).hexdigest()[:16]
        path = self.cache_dir / f"{symbol}_{key}.csv"
        if path.exists() and not refresh:
            frame = pd.read_csv(path, index_col="date", parse_dates=True)
            return validate_ohlcv(frame, symbol)

        frame: pd.DataFrame | None = None
        last_error: MarketDataError | None = None
        retry_delays = self.retry_delays_seconds
        for attempt in range(len(retry_delays) + 1):
            raw = yf.download(
                symbol,
                start=start,
                end=end,
                auto_adjust=True,
                actions=False,
                progress=False,
                threads=False,
                timeout=self.download_timeout,
            )
            if raw.empty:
                last_error = MarketDataError("no market data returned")
                if attempt < len(retry_delays):
                    time.sleep(retry_delays[attempt])
                continue
            if isinstance(raw.columns, pd.MultiIndex):
                raw.columns = raw.columns.get_level_values(0)
            candidate = raw.rename(columns=str.lower)[list(REQUIRED_COLUMNS)].copy()
            candidate.index = pd.DatetimeIndex(candidate.index).tz_localize(None)
            candidate.index.name = "date"
            try:
                frame = validate_ohlcv(candidate, symbol)
                break
            except MarketDataError as exc:
                # Yahoo occasionally returns a transient malformed adjusted bar.
                # Retry the complete request rather than caching or silently repairing it.
                last_error = exc
                if attempt < len(retry_delays):
                    time.sleep(retry_delays[attempt])
        if frame is None:
            raise last_error or MarketDataError("market data download failed")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        frame.to_csv(path)
        return frame


def validate_ohlcv(frame: pd.DataFrame, symbol: str = "asset") -> pd.DataFrame:
    frame = frame.copy()
    frame.columns = [str(column).lower() for column in frame.columns]
    missing = set(REQUIRED_COLUMNS) - set(frame.columns)
    if missing:
        raise MarketDataError(f"missing columns: {sorted(missing)}")
    frame = frame.loc[~frame.index.duplicated(keep="last"), list(REQUIRED_COLUMNS)].sort_index()
    frame = frame.apply(pd.to_numeric, errors="coerce").dropna(subset=["open", "close"])
    if not frame.index.is_monotonic_increasing:
        raise MarketDataError("dates are not monotonic")
    if (frame[["open", "high", "low", "close"]] <= 0).any().any():
        raise MarketDataError(f"{symbol} contains non-positive prices")
    # Independently adjusted Yahoo fields can differ by a few floating-point
    # units even when the economic bar is valid. Keep a machine-scale relative
    # tolerance while still rejecting any material OHLC inconsistency.
    tolerance = frame["close"].abs().clip(lower=1.0) * 1e-10
    invalid_range = (frame["high"] < frame[["open", "close", "low"]].max(axis=1) - tolerance) | (
        frame["low"] > frame[["open", "close", "high"]].min(axis=1) + tolerance
    )
    if invalid_range.any():
        raise MarketDataError(f"{symbol} contains invalid OHLC ranges")
    if len(frame) < 60:
        raise MarketDataError(f"{symbol} has only {len(frame)} usable sessions")
    return frame


def synthetic_market_data(
    symbols: list[str], periods: int = 1_000, seed: int = 7
) -> dict[str, pd.DataFrame]:
    """Deterministic regime-switching data for tests and the offline demo."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2018-01-02", periods=periods)
    market = rng.normal(0.00025, 0.009, periods)
    market[periods // 3 : periods // 3 + 70] += -0.0025
    market[2 * periods // 3 : 2 * periods // 3 + 100] += 0.0012
    result: dict[str, pd.DataFrame] = {}
    for index, symbol in enumerate(symbols):
        returns = 0.7 * market + rng.normal(0.0001, 0.006 + index * 0.0005, periods)
        close = (100 + index * 20) * np.exp(np.cumsum(returns))
        overnight = rng.normal(0, 0.002, periods)
        open_ = close * np.exp(overnight)
        high = np.maximum(open_, close) * (1 + rng.uniform(0, 0.006, periods))
        low = np.minimum(open_, close) * (1 - rng.uniform(0, 0.006, periods))
        result[symbol] = pd.DataFrame(
            {
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "volume": rng.integers(1_000_000, 10_000_000, periods),
            },
            index=dates,
        )
        result[symbol].index.name = "date"
    return result
