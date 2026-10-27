import json
import tempfile
from pathlib import Path

import pytest

from nightshift import ns
from nightshift.exchange import serve


@pytest.fixture
def socket_env(exchange, monkeypatch):
    path = Path(tempfile.mkdtemp(dir="/tmp")) / "ns.sock"
    server = serve(exchange, path)
    monkeypatch.setenv("NS_SOCKET", str(path))
    yield
    server.shutdown()
    server.server_close()


def run(capsys, *argv):
    code = ns.main(list(argv))
    out = capsys.readouterr().out
    if argv[0] in ("markets", "history"):
        return code, [json.loads(line) for line in out.splitlines()]
    return code, json.loads(out)


def test_agent_can_trade_through_the_socket(socket_env, capsys):
    code, out = run(capsys, "buy", "kalshi:TEST-1", "yes", "30", "--p-yes", "0.55", "--note", "n")
    assert code == 0 and out["outcome"] == "YES" and out["note"] == "n"
    code, out = run(capsys, "status")
    assert out["positions"][0]["market"] == "kalshi:TEST-1"
    code, out = run(capsys, "markets", "--hours", "24")
    assert out[0]["id"] == "kalshi:TEST-1"
    code, out = run(capsys, "market", "kalshi:TEST-1")
    assert out["books"]["YES"]["asks"][0] == [0.42, 50.0]
    code, out = run(capsys, "forecast", "kalshi:TEST-1", "0.3")
    assert out["kind"] == "forecast"
    code, out = run(capsys, "history")
    assert [e["kind"] for e in out] == ["fill", "forecast"]


def test_refusals_exit_nonzero_with_a_reason(socket_env, capsys):
    code, out = run(capsys, "sell", "kalshi:TEST-1", "NO", "5")
    assert code == 1 and "hold no" in out["error"]


def test_without_a_session_ns_explains_itself(monkeypatch, capsys):
    monkeypatch.delenv("NS_SOCKET", raising=False)
    code, out = run(capsys, "status")
    assert code == 1 and "inside a session" in out["error"]
