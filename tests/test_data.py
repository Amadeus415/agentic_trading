import pandas as pd
import pytest

from edgecraft.data import MarketDataError, synthetic_market_data, validate_ohlcv


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
