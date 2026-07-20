from edgecraft.data import synthetic_market_data
from edgecraft.models import BacktestRequest, StrategySpec, ValidationConfig
from edgecraft.walkforward import walk_forward_validate


def test_walk_forward_uses_non_overlapping_oos_windows():
    request = BacktestRequest(
        symbols=["AAA"],
        initial_capital=500,
        contribution_amount=20,
        strategies=[
            StrategySpec(name="plain_dca"),
            StrategySpec(name="value_tilted_dca"),
            StrategySpec(
                name="trend_vol_target",
                params={"fast_window": 20, "slow_window": 60},
            ),
        ],
        validation=ValidationConfig(bootstrap_samples=0, cscv_slices=4),
    )
    result = walk_forward_validate(
        synthetic_market_data(["AAA"], periods=300),
        request,
        train_sessions=100,
        test_sessions=40,
        step_sessions=40,
    )

    assert result["summary"]["folds"] == 5
    assert result["summary"]["oos_sessions"] == 200
    assert result["method"]["test_windows_overlap"] is False
    assert all(
        left["test_end"] < right["test_start"]
        for left, right in zip(result["folds"], result["folds"][1:], strict=False)
    )
