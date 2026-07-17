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
            "validation": {"bootstrap_samples": 0, "bootstrap_block_size": 20, "cscv_slices": 4, "random_seed": 7},
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["results"][0]["metrics"]["fills"] > 0
