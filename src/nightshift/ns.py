"""`ns`: the agent's only handle on its account.

Every command prints JSON. Market IDs look like polymarket:<id> or
kalshi:<ticker>; outcomes are YES or NO; prices are dollars per share that
pays $1 if the outcome wins.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys

EXAMPLES = """\
examples:
  ns status                                   cash, positions at the bid, account value
  ns markets --hours 48 --query election      open markets closing within 48 hours
  ns market kalshi:KXFEDDECISION-26DEC-H0     rules, both order books, fees
  ns buy polymarket:608547 NO 50 --p-yes 0.1 --note "why"   up to $50 on NO; you think YES is 10%
  ns sell polymarket:608547 NO all            sell back into the bids
  ns forecast kalshi:KXCPI-26NOV-T3.0 0.35    record P(YES); scored against the market
  ns history                                  your fills, settlements and forecasts
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ns",
        description="Trade your simulated prediction-market account.",
        epilog=EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="cash, positions valued at the best bid, account value")
    p = sub.add_parser("markets", help="list open YES/NO markets, busiest first")
    p.add_argument("--hours", type=float, default=168, help="closing within this many hours")
    p.add_argument("--min-hours", type=float, default=0, help="closing after this many hours")
    p.add_argument("--venue", choices=["polymarket", "kalshi"])
    p.add_argument("--query", help="words that must all appear in the question")
    p.add_argument("--limit", type=int, default=50)
    p = sub.add_parser("market", help="one market: rules, order books, fees")
    p.add_argument("id")
    p = sub.add_parser("buy", help="spend up to DOLLARS on an outcome at the asks")
    p.add_argument("id")
    p.add_argument("outcome", choices=["YES", "NO", "yes", "no"])
    p.add_argument("dollars", type=float)
    p.add_argument(
        "--p-yes", type=float, required=True, help="your probability that YES wins, as in forecast"
    )
    p.add_argument("--note", default="", help="why, in a sentence or two")
    p = sub.add_parser("sell", help="sell shares into the bids")
    p.add_argument("id")
    p.add_argument("outcome", choices=["YES", "NO", "yes", "no"])
    p.add_argument("shares", help="a whole number, or 'all'")
    p.add_argument("--note", default="")
    p = sub.add_parser("forecast", help="record your probability that YES wins")
    p.add_argument("id")
    p.add_argument("p_yes", type=float)
    p.add_argument("--note", default="")
    p = sub.add_parser("history", help="your fills, settlements and forecasts")
    p.add_argument("--limit", type=int, default=50)

    args = vars(parser.parse_args(argv))
    command = args.pop("command")
    if command == "markets":
        args = {
            "max_hours": args["hours"],
            "min_hours": args["min_hours"],
            "venue": args["venue"],
            "query": args["query"],
            "limit": args["limit"],
        }
    elif command in ("market", "buy", "sell", "forecast"):
        args["market"] = args.pop("id")
        if command == "market":
            args = {"market_id": args.pop("market")}
    response = request({"command": command, "args": args})
    print(json.dumps(response.get("result", response), indent=1))
    return 0 if response.get("ok") else 1


def request(payload: dict) -> dict:
    path = os.environ.get("NS_SOCKET")
    if not path:
        return {"ok": False, "error": "NS_SOCKET is not set; ns only works inside a session"}
    with socket.socket(socket.AF_UNIX) as conn:
        conn.settimeout(300)
        try:
            conn.connect(path)
        except OSError as exc:
            return {"ok": False, "error": f"exchange unavailable: {exc}"}
        conn.sendall((json.dumps(payload) + "\n").encode())
        data = b""
        while not data.endswith(b"\n"):
            chunk = conn.recv(65536)
            if not chunk:
                break
            data += chunk
    return json.loads(data or b'{"ok": false, "error": "no response"}')


if __name__ == "__main__":
    sys.exit(main())
