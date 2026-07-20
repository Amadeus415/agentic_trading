from fastapi.testclient import TestClient

from edgecraft.api import app

client = TestClient(app)


def test_health_and_strategy_catalog():
    assert client.get("/api/health").json()["status"] == "ok"
    catalog = client.get("/api/strategies").json()
    assert {item["name"] for item in catalog} >= {"plain_dca", "conformal_ml"}


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
    assert "How it works" in script.text
    assert "RUN EXPLORER" in script.text
