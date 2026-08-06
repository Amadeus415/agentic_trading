import argparse
import json

import pytest

from edgecraft.cli import _should_exit_nonzero, dispatch, main, operational_readiness


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


@pytest.mark.parametrize(
    ("command", "payload", "expected"),
    [
        ("health", {"ok": False, "detail": "mcp missing"}, True),
        ("health", {"ok": True, "detail": "ready"}, False),
        ("cycle", {"ok": False, "status": "unresolved_orders"}, True),
        ("cycle", {"ok": False, "status": "failed", "idempotent_replay": True}, True),
        ("cycle", {"ok": True, "status": "not_due"}, False),
        ("cycle", {"ok": True, "status": "held"}, False),
        ("cycle", {"ok": True, "status": "risk_rejected"}, False),
        ("cycle", {"ok": True, "status": "shadow_complete"}, False),
        ("cycle", {"ok": True, "status": "completed"}, False),
        ("cycle", {"ok": True, "status": "in_progress"}, False),
        ("readiness", {"ok": False, "reasons": ["halted"]}, False),
        ("autonomy-health", {"ok": False}, False),
        ("cycle", "not-a-dict", False),
        ("cycle", {"status": "failed"}, False),
    ],
)
def test_should_exit_nonzero_for_health_and_cycle(command, payload, expected):
    assert _should_exit_nonzero(command, payload) is expected


def test_main_exits_one_when_cycle_ok_false(monkeypatch, capsys):
    monkeypatch.setattr(
        "edgecraft.cli.dispatch",
        lambda _args: {"ok": False, "status": "unresolved_orders"},
    )
    with pytest.raises(SystemExit) as excinfo:
        main(["cycle", "--mandate", "unused.json"])
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert '"ok": false' in captured.out
    assert "unresolved_orders" in captured.out


@pytest.mark.parametrize(
    "status",
    ["not_due", "held", "risk_rejected", "shadow_complete", "completed", "in_progress"],
)
def test_main_exits_zero_when_cycle_ok_true(monkeypatch, capsys, status):
    monkeypatch.setattr(
        "edgecraft.cli.dispatch",
        lambda _args: {"ok": True, "status": status},
    )
    main(["cycle", "--mandate", "unused.json"])
    captured = capsys.readouterr()
    assert '"ok": true' in captured.out
    assert status in captured.out


def test_main_exits_one_when_health_ok_false(monkeypatch, capsys):
    monkeypatch.setattr(
        "edgecraft.cli.dispatch",
        lambda _args: {"ok": False, "robinhood_mcp": {"configured": False}},
    )
    with pytest.raises(SystemExit) as excinfo:
        main(["health"])
    assert excinfo.value.code == 1
    assert '"ok": false' in capsys.readouterr().out


def test_main_readiness_require_ready_still_exits_two_on_failure(monkeypatch, capsys):
    """Readiness keeps exception path (exit 2); it is not gated by ok=false alone."""
    monkeypatch.setattr(
        "edgecraft.cli.operational_readiness",
        lambda *_args, **_kwargs: {
            "ok": False,
            "reasons": ["mandate is disabled"],
        },
    )
    with pytest.raises(SystemExit) as excinfo:
        main(
            [
                "readiness",
                "--mandate",
                "unused.json",
                "--require-ready",
            ]
        )
    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert '"ok": false' in err
    assert "mandate is disabled" in err


def test_main_readiness_without_require_ready_exits_zero_even_when_not_ok(monkeypatch, capsys):
    monkeypatch.setattr(
        "edgecraft.cli.operational_readiness",
        lambda *_args, **_kwargs: {
            "ok": False,
            "reasons": ["mandate is disabled"],
        },
    )
    main(["readiness", "--mandate", "unused.json"])
    captured = capsys.readouterr()
    assert '"ok": false' in captured.out
    assert "mandate is disabled" in captured.out


def test_paper_only_cycle_rejects_live_mandate_before_runtime(tmp_path, capsys):
    policy = tmp_path / "policy.json"
    policy.write_text(
        json.dumps(
            {
                "policy_name": "live",
                "trading_enabled": True,
                "allowed_symbols": ["SPY"],
            }
        )
    )
    mandate = tmp_path / "mandate.json"
    mandate.write_text(
        json.dumps(
            {
                "mandate_id": "live",
                "goal": "Must be rejected by the paper-only boundary.",
                "mode": "live",
                "weekly_budget": "1",
                "universe": ["SPY"],
                "strategic_weights": {"SPY": "1"},
                "policy_path": str(policy),
                "external_context_path": "context.json",
            }
        )
    )

    with pytest.raises(SystemExit) as excinfo:
        main(["cycle", "--mandate", str(mandate), "--paper-only"])

    assert excinfo.value.code == 2
    assert "paper-only cycles require a shadow mandate" in capsys.readouterr().err


def test_paper_only_cycle_rejects_trading_enabled_policy(tmp_path, capsys):
    policy = tmp_path / "policy.json"
    policy.write_text(
        json.dumps(
            {
                "policy_name": "unsafe-shadow",
                "trading_enabled": True,
                "allowed_symbols": ["SPY"],
            }
        )
    )
    mandate = tmp_path / "mandate.json"
    mandate.write_text(
        json.dumps(
            {
                "mandate_id": "unsafe_shadow",
                "goal": "Must be rejected by the paper-only policy boundary.",
                "mode": "shadow",
                "weekly_budget": "1",
                "universe": ["SPY"],
                "strategic_weights": {"SPY": "1"},
                "policy_path": str(policy),
            }
        )
    )

    with pytest.raises(SystemExit) as excinfo:
        main(["cycle", "--mandate", str(mandate), "--paper-only"])

    assert excinfo.value.code == 2
    assert "paper-only cycles require trading_enabled=false" in capsys.readouterr().err
