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
    result = MarketDataProvider(tmp_path).load(["AAA"], "2020-01-01", "2021-01-01")

    assert calls == 2
    pd.testing.assert_frame_equal(result["AAA"], valid, check_freq=False)
