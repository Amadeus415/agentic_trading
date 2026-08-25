#!/usr/bin/env python3
"""Fail-closed Codex PreToolUse guard: never allow broker mutation tools."""

from __future__ import annotations

import json
import sys
from typing import Any

PROTECTED_TOOLS = {
    "place_equity_order",
    "cancel_equity_order",
    "place_option_order",
    "cancel_option_order",
}


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return _deny("Edgecraft could not parse the Codex tool event.")
    tool_name = str(event.get("tool_name", ""))
    if _is_protected(tool_name, event.get("tool_input", {})):
        return _deny(
            "Edgecraft is paper-only. Broker mutation tools are blocked: "
            f"{tool_name or 'unknown tool'}."
        )
    return 0


def _is_protected(tool_name: str, tool_input: Any) -> bool:
    lowered = tool_name.lower()
    if any(name in lowered for name in PROTECTED_TOOLS):
        return True
    blob = json.dumps(tool_input, default=str).lower() if tool_input else ""
    return any(name in blob for name in PROTECTED_TOOLS)


def _deny(reason: str) -> int:
    json.dump({"decision": "deny", "reason": reason}, sys.stdout)
    print(file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
