from fastapi.testclient import TestClient

from edgecraft.api import app

client = TestClient(app)


def test_health_has_restrictive_security_headers():
    health = client.get("/api/health")
    assert health.json()["status"] == "ok"
    assert health.headers["x-content-type-options"] == "nosniff"
    assert health.headers["x-frame-options"] == "DENY"
    assert "default-src 'self'" in health.headers["content-security-policy"]
    assert "access-control-allow-origin" not in health.headers


def test_autonomy_health_and_metrics(tmp_path, monkeypatch):
    monkeypatch.setenv("EDGECRAFT_LEDGER", str(tmp_path / "state.db"))
    health = client.get("/api/autonomy/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ready"

    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    assert "edgecraft_trading_halted 0" in metrics.text


def test_frontend_serves_control_plane():
    index = client.get("/")
    script = client.get("/app.js")
    assert index.status_code == 200
    assert script.status_code == 200
    assert "Portfolio control plane" in index.text
    assert "Trading history" in script.text
    assert "Agent runs" in script.text
    assert "A model can suggest. It cannot authorize itself." in script.text
    assert "/api/control-plane" in script.text
    assert "/api/trades/" in script.text
    assert "Complete record" in script.text


def test_control_plane_exposes_redacted_ledger_read_model(tmp_path, monkeypatch):
    monkeypatch.setenv("EDGECRAFT_LEDGER", str(tmp_path / "control-plane.db"))
    response = client.get("/api/control-plane")
    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "audit_ledger"
    assert payload["has_history"] is False
    assert payload["health"]["status"] == "ready"
    assert payload["runs"] == []
    assert payload["trades"] == []

    missing_trade = client.get("/api/trades/not-a-real-order")
    assert missing_trade.status_code == 404
