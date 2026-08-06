import pandas as pd
import pytest

from edgecraft.data import (
    MarketDataError,
    MarketDataProvider,
    synthetic_market_data,
    validate_ohlcv,
)


def test_synthetic_data_is_deterministic_and_valid():
    first = synthetic_market_data(["AAA", "BBB"], periods=300, seed=11)
    second = synthetic_market_data(["AAA", "BBB"], periods=300, seed=11)
    pd.testing.assert_frame_equal(first["AAA"], second["AAA"])
    assert len(first["BBB"]) == 300
    assert (first["AAA"]["high"] >= first["AAA"]["low"]).all()


def test_validation_rejects_impossible_bar():
    frame = synthetic_market_data(["AAA"], periods=100)["AAA"]
    frame.loc[frame.index[5], "high"] = frame.loc[frame.index[5], "low"] - 1
    with pytest.raises(MarketDataError, match="invalid OHLC"):
        validate_ohlcv(frame)


def test_validation_allows_machine_scale_adjustment_rounding():
    frame = synthetic_market_data(["AAA"], periods=100)["AAA"]
    date = frame.index[5]
    frame.loc[date, "open"] = frame.loc[date, "close"]
    frame.loc[date, "high"] = frame.loc[date, "close"] - frame.loc[date, "close"] * 1e-12

    validated = validate_ohlcv(frame)

    assert len(validated) == len(frame)


def test_provider_retries_transient_invalid_download(monkeypatch, tmp_path):
    valid = synthetic_market_data(["AAA"], periods=100)["AAA"]
    invalid = valid.copy()
    invalid.loc[invalid.index[5], "high"] = invalid.loc[invalid.index[5], "low"] - 1
    responses = iter([invalid, valid])
    calls = 0

    def fake_download(*args, **kwargs):
        nonlocal calls
        calls += 1
        return next(responses)

    monkeypatch.setattr("edgecraft.data.yf.download", fake_download)
    monkeypatch.setattr("edgecraft.data.time.sleep", lambda _: None)
    result = MarketDataProvider(tmp_path).load(["AAA"], "2020-01-01", "2021-01-01")

    assert calls == 2
    pd.testing.assert_frame_equal(result["AAA"], valid, check_freq=False)


def test_provider_backs_off_after_empty_downloads(monkeypatch, tmp_path):
    valid = synthetic_market_data(["AAA"], periods=100)["AAA"]
    responses = iter([pd.DataFrame(), pd.DataFrame(), valid])
    calls = 0
    delays: list[float] = []

    def fake_download(*args, **kwargs):
        nonlocal calls
        calls += 1
        return next(responses)

    monkeypatch.setattr("edgecraft.data.yf.download", fake_download)
    monkeypatch.setattr("edgecraft.data.time.sleep", delays.append)

    result = MarketDataProvider(tmp_path).load(["AAA"], "2020-01-01", "2021-01-01")

    assert calls == 3
    assert delays == [0.5, 1.5]
    pd.testing.assert_frame_equal(result["AAA"], valid, check_freq=False)


def test_provider_defaults_preserve_retry_and_timeout_configuration():
    provider = MarketDataProvider()

    assert provider.retry_delays_seconds == (0.5, 1.5, 3.0)
    assert provider.download_timeout == 20.0


def test_provider_honors_injected_retry_delays_and_timeout(monkeypatch, tmp_path):
    timeouts: list[float] = []
    delays: list[float] = []
    calls = 0

    def fake_download(*args, **kwargs):
        nonlocal calls
        calls += 1
        timeouts.append(kwargs["timeout"])
        return pd.DataFrame()

    monkeypatch.setattr("edgecraft.data.yf.download", fake_download)
    monkeypatch.setattr("edgecraft.data.time.sleep", delays.append)

    provider = MarketDataProvider(
        tmp_path,
        retry_delays_seconds=(0.25, 0.75),
        download_timeout=8.0,
    )
    with pytest.raises(MarketDataError, match="no market data returned"):
        provider.load(["AAA"], "2020-01-01", "2021-01-01")

    assert calls == 3
    assert timeouts == [8.0, 8.0, 8.0]
    assert delays == [0.25, 0.75]


def test_provider_with_empty_retry_delays_makes_single_attempt(monkeypatch, tmp_path):
    calls = 0
    delays: list[float] = []
    timeouts: list[float] = []

    def fake_download(*args, **kwargs):
        nonlocal calls
        calls += 1
        timeouts.append(kwargs["timeout"])
        return pd.DataFrame()

    monkeypatch.setattr("edgecraft.data.yf.download", fake_download)
    monkeypatch.setattr("edgecraft.data.time.sleep", delays.append)

    provider = MarketDataProvider(
        tmp_path,
        retry_delays_seconds=(),
        download_timeout=8.0,
    )
    with pytest.raises(MarketDataError, match="no market data returned"):
        provider.load(["AAA"], "2020-01-01", "2021-01-01")

    assert calls == 1
    assert timeouts == [8.0]
    assert delays == []
