from fastapi.testclient import TestClient

from edgecraft.api import app

client = TestClient(app)


def test_health_and_strategy_catalog():
    assert client.get("/api/health").json()["status"] == "ok"
    catalog = client.get("/api/strategies").json()
    assert {item["name"] for item in catalog} >= {"plain_dca", "conformal_ml"}


def test_autonomy_health_and_metrics(tmp_path, monkeypatch):
    monkeypatch.setenv("EDGECRAFT_LEDGER", str(tmp_path / "state.db"))
    health = client.get("/api/autonomy/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ready"

    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    assert "edgecraft_trading_halted 0" in metrics.text


def test_synthetic_backtest_endpoint():
    response = client.post(
        "/api/backtests?data_source=synthetic",
        json={
            "symbols": ["AAA"],
            "initial_capital": 5000,
            "contribution_amount": 50,
            "contribution_frequency": "weekly",
            "strategies": [{"name": "plain_dca", "params": {}}],
            "validation": {
                "bootstrap_samples": 0,
                "bootstrap_block_size": 20,
                "cscv_slices": 4,
                "random_seed": 7,
            },
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["results"][0]["metrics"]["fills"] > 0
    assert {"equity", "drawdown", "cash", "net_invested", "exposure"} <= set(
        payload["results"][0]["series"][0]
    )


def test_frontend_serves_about_and_run_explorer():
    index = client.get("/")
    script = client.get("/app.js")
    assert index.status_code == 200
    assert script.status_code == 200
    assert "Autonomy Workbench" in index.text
    assert "How it works" in script.text
    assert "RUN REAL POLICY GATE" in script.text
    assert "/api/learn/scenarios" in script.text
    assert "RUN EXPLORER" in script.text


def test_learning_guide_traces_real_system_boundaries():
    response = client.get("/api/learn")
    assert response.status_code == 200
    payload = response.json()
    assert payload["principle"] == "Models propose. Typed policy authorizes. The broker executes."
    assert [step["id"] for step in payload["cycle"]] == [
        "mandate",
        "observe",
        "decide",
        "gate",
        "execute",
        "reconcile",
    ]
    assert "get_accounts" in payload["protocol"]["refresh_tools"]


def test_learning_scenario_uses_the_real_policy_gate():
    approved = client.post("/api/learn/scenarios", json={})
    assert approved.status_code == 200
    assert approved.json()["outcome"] == "shadow_complete"
    assert approved.json()["risk"]["approved_for_review"]
    assert sum(order["notional"] for order in approved.json()["orders"]) == 10

    blocked = client.post(
        "/api/learn/scenarios",
        json={"weekly_budget": 10, "vti_notional": 11, "vxus_notional": 0, "bnd_notional": 0},
    )
    assert blocked.status_code == 200
    assert blocked.json()["outcome"] == "risk_rejected"
    assert any("cycle budget" in item for item in blocked.json()["risk"]["violations"])


def test_learning_scenario_surfaces_stale_data_and_open_orders():
    response = client.post(
        "/api/learn/scenarios",
        json={"snapshot_age_seconds": 600, "quote_age_seconds": 600, "has_open_order": True},
    )
    assert response.status_code == 200
    violations = response.json()["risk"]["violations"]
    assert any("snapshot is stale" in item for item in violations)
    assert any("quote is stale" in item for item in violations)
    assert any("open broker order" in item for item in violations)
