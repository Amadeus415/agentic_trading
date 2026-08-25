from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _module():
    path = ROOT / "scripts" / "deny_broker_tools.py"
    spec = importlib.util.spec_from_file_location("deny_broker_tools", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_deny_broker_tools_blocks_place_equity_order(monkeypatch, capsys) -> None:
    module = _module()
    monkeypatch.setattr(
        module.sys,
        "stdin",
        io.StringIO(
            json.dumps(
                {
                    "tool_name": "mcp__robinhood_trading__place_equity_order",
                    "tool_input": {"symbol": "SPY"},
                }
            )
        ),
    )
    assert module.main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["decision"] == "deny"
    assert "paper-only" in payload["reason"]


def test_deny_broker_tools_allows_unrelated_tools(monkeypatch, capsys) -> None:
    module = _module()
    monkeypatch.setattr(
        module.sys,
        "stdin",
        io.StringIO(json.dumps({"tool_name": "web.search", "tool_input": {"query": "AAPL"}})),
    )
    assert module.main() == 0
    assert capsys.readouterr().out == ""
