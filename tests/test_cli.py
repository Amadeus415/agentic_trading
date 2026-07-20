import argparse
import json

from edgecraft.cli import dispatch


def test_cli_backtest_and_portfolio_commands(tmp_path):
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
        argparse.Namespace(command="backtest", config=config, data_source="synthetic")
    )
    assert result["meta"]["strategies_tested"] == 1

    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(
        json.dumps(
            {
                "account_id": "test",
                "agentic_allowed": True,
                "buying_power": 200,
                "portfolio_value": 500,
                "as_of": "2026-07-19T18:00:00Z",
                "positions": [
                    {
                        "symbol": "SPY",
                        "quantity": 0.5,
                        "market_price": 600,
                        "average_cost": 550,
                    }
                ],
            }
        )
    )
    analysis = dispatch(argparse.Namespace(command="portfolio", snapshot=snapshot))
    assert analysis["position_count"] == 1
    assert analysis["positions"][0]["unrealized_pnl"] == 25
