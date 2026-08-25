import argparse
import json

from edgecraft.cli import dispatch


def test_cli_backtest_synthetic(tmp_path):
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "symbols": ["AAA"],
                "initial_capital": 500,
                "contribution_amount": 25,
                "strategies": [{"name": "plain_dca"}],
                "validation": {
                    "bootstrap_samples": 0,
                    "bootstrap_block_size": 20,
                    "cscv_slices": 4,
                    "random_seed": 7,
                },
            }
        )
    )
    result = dispatch(
        argparse.Namespace(
            command="backtest",
            config=config,
            data_source="synthetic",
            cost_multiplier=1.0,
        )
    )
    assert result["meta"]["strategies_tested"] == 1
