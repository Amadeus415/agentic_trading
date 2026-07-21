import argparse
import json

from edgecraft.cli import dispatch, operational_readiness


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


def test_live_readiness_requires_explicit_production_controls(tmp_path, monkeypatch):
    (tmp_path / ".codex").mkdir()
    (tmp_path / ".codex" / "hooks.json").write_text("{}")
    (tmp_path / "context.json").write_text("{}")
    policy = tmp_path / "policy.json"
    policy.write_text(
        json.dumps(
            {
                "policy_name": "readiness-live",
                "trading_enabled": True,
                "allowed_symbols": ["SPY"],
                "min_cash_reserve": 0,
                "allowed_market_sessions": ["regular"],
                "max_drawdown_fraction": 0.1,
                "max_order_adv_fraction": 0.001,
                "max_rolling_7d_turnover": 0.5,
                "max_spread_bps": 25,
                "min_shadow_cycles_before_live": 0,
            }
        )
    )
    mandate = tmp_path / "mandate.json"
    mandate.write_text(
        json.dumps(
            {
                "mandate_id": "readiness_live",
                "goal": "Exercise explicit production readiness controls.",
                "mode": "live",
                "weekly_budget": "10",
                "universe": ["SPY"],
                "strategic_weights": {"SPY": "1"},
                "policy_path": str(policy),
                "external_context_path": str(tmp_path / "context.json"),
            }
        )
    )
    monkeypatch.setattr("edgecraft.cli.shutil.which", lambda name: f"/tmp/{name}")

    ready = operational_readiness(tmp_path, mandate, tmp_path / "state.db")

    assert ready["ok"]
    raw = json.loads(policy.read_text())
    raw.pop("max_spread_bps")
    policy.write_text(json.dumps(raw))
    blocked = operational_readiness(tmp_path, mandate, tmp_path / "state.db")
    assert not blocked["ok"]
    assert any("max_spread_bps" in reason for reason in blocked["reasons"])
