"""Turn runs into results: one JSON document the website and the paper read.

Three questions, in order of statistical power:

1. Forecast skill: on resolved markets, did the agent's first stated
   probability beat the market's own price at that moment (Brier score)?
2. Edge: on positions that closed, how many cents did each dollar staked
   return after fees?
3. Return: what is the account worth, valued at the bid?

Markets on the same event resolve together, so every interval resamples whole
events (a cluster bootstrap), never single markets.
"""

from __future__ import annotations

import json
import random
import subprocess
import urllib.parse
from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal
from statistics import mean
from typing import Any

from nightshift import BENCHMARK_VERSION
from nightshift.ledger import fold, now_iso
from nightshift.runner import REPO, Run, _at, load_runs, notes
from nightshift.venues import VenueError, get_json

PROVISIONAL_DAYS = 14
BOOTSTRAP = 2000


def bootstrap(clusters: dict[str, list[tuple[float, float]]], stat, seed: int = 0):
    """95% interval of stat(pairs) when whole clusters are resampled."""
    keys = list(clusters)
    if len(keys) < 2:
        return None
    rng = random.Random(seed)
    draws = []
    for _ in range(BOOTSTRAP):
        pairs = [pair for k in rng.choices(keys, k=len(keys)) for pair in clusters[k]]
        value = stat(pairs)
        if value is not None:
            draws.append(value)
    return _interval(draws)


def _interval(draws: list[float]) -> list[float] | None:
    if len(draws) < 100:
        return None
    draws.sort()
    return [draws[int(0.025 * len(draws))], draws[int(0.975 * len(draws)) - 1]]


def bootstrap_difference(a: dict[str, list], b: dict[str, list], stat, seed: int = 0):
    """95% interval of stat(a) - stat(b), resampling each side's clusters independently."""
    if len(a) < 2 or len(b) < 2:
        return None
    rng = random.Random(seed)
    draws = []
    for _ in range(BOOTSTRAP):
        sa = stat([p for k in rng.choices(list(a), k=len(a)) for p in a[k]])
        sb = stat([p for k in rng.choices(list(b), k=len(b)) for p in b[k]])
        if sa is not None and sb is not None:
            draws.append(sa - sb)
    return _interval(draws)


def _edge(pairs: list[tuple[float, float]]) -> float | None:
    staked = sum(s for s, _ in pairs)
    return sum(p for _, p in pairs) / staked if staked else None


def _skill(pairs: list[tuple[float, float]]) -> float | None:
    """Brier skill against the market: 1 - agent Brier / market Brier."""
    market = mean(m for _, m in pairs)
    return 1 - mean(a for a, _ in pairs) / market if market else None


def closed_positions(
    events: list[dict[str, Any]], final_marks: dict[tuple[str, str], Decimal] | None = None
) -> list[dict[str, Any]]:
    """Each holding from first buy until its shares return to zero, with its P&L.

    Given the final marks of a finished run, holdings still open close at them,
    so selling winners and keeping losers past the window cannot flatter edge.
    """
    open_: dict[tuple[str, str], dict[str, Any]] = {}
    closed = []
    for e in events:
        if e["kind"] not in ("fill", "settle"):
            continue
        key = (e["market"], e["outcome"])
        pos = open_.setdefault(
            key,
            {
                "market": e["market"],
                "outcome": e["outcome"],
                "event": e.get("event", e["market"]),
                "question": e.get("question", ""),
                "opened_at": e["at"],
                "shares": Decimal(0),
                "staked": Decimal(0),
                "cash": Decimal(0),
            },
        )
        pos["cash"] += Decimal(e["cash"])
        if e["kind"] == "settle":
            pos["shares"] = Decimal(0)
            pos["how"] = "settled"
        elif e["side"] == "buy":
            pos["shares"] += Decimal(e["shares"])
            pos["staked"] -= Decimal(e["cash"])
        else:
            pos["shares"] -= Decimal(e["shares"])
            pos["how"] = "sold"
        if pos["shares"] == 0:
            closed.append({**pos, "closed_at": e["at"], "pnl": pos["cash"]})
            del open_[key]
    for key, pos in open_.items() if final_marks is not None else ():
        value = pos["shares"] * final_marks.get(key, Decimal(0))
        closed.append({**pos, "how": "open at end", "closed_at": None, "pnl": pos["cash"] + value})
    return closed


def first_forecasts(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The first probability stated per market, from forecasts and buys alike."""
    first: dict[str, dict[str, Any]] = {}
    for e in events:
        if e.get("market") is None or e["market"] in first:
            continue
        stated = e["kind"] == "forecast" or (e["kind"] == "fill" and e["side"] == "buy")
        if not stated or e.get("p_yes") is None:
            continue
        p_yes = Decimal(e["p_yes"])
        if e.get("market_yes") is None:
            continue
        first[e["market"]] = {
            "market": e["market"],
            "event": e.get("event", e["market"]),
            "question": e.get("question", ""),
            "at": e["at"],
            "p_yes": float(p_yes),
            "market_yes": float(e["market_yes"]),
        }
    return list(first.values())


def score_run(run: Run) -> dict[str, Any]:
    ledger = run.ledger()
    try:
        events = ledger.events()
        verified = ledger.verify()
    finally:
        ledger.close()
    cash0 = float(events[0]["cash"])
    series = [[run.started_at, cash0]] + [
        [e["at"], float(e["value"])] for e in events if e["kind"] == "mark"
    ]
    value = series[-1][1]
    peak, drawdown = cash0, 0.0
    for _, v in series:
        peak = max(peak, v)
        drawdown = max(drawdown, 1 - v / peak)

    acct = fold(events)
    finished = not run.active() and acct.marked_at is not None and acct.marked_at >= run.ends_at
    closed = closed_positions(events, acct.marks if finished else None)
    by_event: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for pos in closed:
        by_event[pos["event"]].append((float(pos["staked"]), float(pos["pnl"])))
    pairs = [p for ps in by_event.values() for p in ps]

    outcomes = {e["market"]: float(e["payout_yes"]) for e in events if e["kind"] == "resolve"}
    forecasts = first_forecasts(events)
    scored: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for f in forecasts:
        if f["market"] in outcomes:
            y = outcomes[f["market"]]
            scored[f["event"]].append(((f["p_yes"] - y) ** 2, (f["market_yes"] - y) ** 2))
    brier_pairs = [p for ps in scored.values() for p in ps]

    sessions = run.sessions()
    fills = [e for e in events if e["kind"] == "fill"]
    holding = [
        {
            "market": p.market,
            "outcome": p.outcome,
            "question": p.question,
            "shares": float(p.shares),
            "cost": round(float(p.cost), 2),
            "bid": float(acct.marks[(p.market, p.outcome)])
            if (p.market, p.outcome) in acct.marks
            else None,
        }
        for p in acct.positions.values()
    ]
    now = datetime.now(UTC)
    days = (min(now, _at(run.ends_at)) - _at(run.started_at)).total_seconds() / 86400
    return {
        "id": run.id,
        "kind": run.kind,
        "model": run.model,
        "harness": run.harness,
        "arm": run.arm,
        "strategy": run.strategy,
        "started_at": run.started_at,
        "ends_at": run.ends_at,
        "status": "live" if run.active() else "finished",
        "days": round(days, 2),
        "provisional": days < PROVISIONAL_DAYS,
        "benchmark": run.benchmark,
        "code": run.code,
        "ledger_events": verified,
        "value": round(value, 2),
        "return": round(value / cash0 - 1, 4),
        "max_drawdown": round(drawdown, 4),
        "fees": round(sum(float(e["fee"]) for e in fills), 2),
        "fills": len(fills),
        "closed_positions": len(closed),
        "wins": sum(1 for p in closed if p["pnl"] > 0),
        "edge": None if not pairs else round(_edge(pairs), 4),
        "edge_ci": bootstrap(by_event, _edge),
        "forecasts": len(forecasts),
        "forecasts_resolved": len(brier_pairs),
        "brier": None if not brier_pairs else round(mean(a for a, _ in brier_pairs), 4),
        "market_brier": None if not brier_pairs else round(mean(m for _, m in brier_pairs), 4),
        "skill": None if not brier_pairs else _round(_skill(brier_pairs)),
        "skill_ci": bootstrap(scored, _skill),
        "sessions": len(sessions),
        "cost_usd": round(sum(s.get("cost_usd") or 0 for s in sessions), 2),
        "output_tokens": sum(s.get("output_tokens") or 0 for s in sessions),
        "lines_changed": sum(s.get("insertions", 0) + s.get("deletions", 0) for s in sessions),
        "sessions_changed": sum(1 for s in sessions if s.get("insertions") or s.get("deletions")),
        "series": series,
        "trades": [_public_fill(e) for e in fills],
        "holding": holding,
        "marked_at": acct.marked_at,
        "closed": [
            {k: (float(v) if isinstance(v, Decimal) else v) for k, v in p.items()} for p in closed
        ],
        "session_log": [
            {
                k: s.get(k)
                for k in (
                    "session",
                    "started_at",
                    "ended_at",
                    "cost_usd",
                    "turns",
                    "tool_calls",
                    "output_tokens",
                    "timed_out",
                    "is_error",
                    "harness",
                    "denials",
                    "tmp_refs",
                    "commit",
                    "files_changed",
                    "insertions",
                    "deletions",
                    "files",
                    "summary",
                )
            }
            for s in sessions
        ],
        "_scored": scored,  # per-event Brier pairs for the arm comparison; not published
    }


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 4)


def _public_fill(e: dict[str, Any]) -> dict[str, Any]:
    keys = ("at", "market", "question", "outcome", "side", "shares", "price", "fee", "p_yes")
    keys += ("market_yes", "note")
    out = {k: e.get(k) for k in keys}
    for k in ("shares", "price", "fee", "p_yes", "market_yes"):
        out[k] = None if out[k] is None else float(out[k])
    out["session"] = e.get("session")
    return out


def compare_arms(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Evolving vs frozen, per model: the benchmark's self-improvement test.

    Returns are compared by replicate; forecast skill pools each arm's resolved
    forecasts by event and reports a bootstrap interval for the difference (H2).
    """
    groups: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for r in runs:
        if r["kind"] == "agent":
            groups[r["model"]][r["arm"]].append(r)
    rows = []
    for model, arms in sorted(groups.items()):
        row: dict[str, Any] = {"model": model}
        for arm in ("evolving", "frozen"):
            members = arms.get(arm, [])
            row[arm] = {
                "replicates": len(members),
                "return": [m["return"] for m in members],
                "skill": [m["skill"] for m in members],
                "mean_return": round(mean(m["return"] for m in members), 4) if members else None,
            }
            pooled: dict[str, list] = defaultdict(list)
            for m in members:
                for event, pairs in m.get("_scored", {}).items():
                    pooled[event] += pairs
            row[arm]["pooled_skill"] = _round(
                _skill([p for ps in pooled.values() for p in ps]) if pooled else None
            )
            row[arm]["resolved"] = sum(len(ps) for ps in pooled.values())
            row[arm]["_pooled"] = pooled
        e, f = row["evolving"], row["frozen"]
        if e["mean_return"] is not None and f["mean_return"] is not None:
            row["difference"] = round(e["mean_return"] - f["mean_return"], 4)
        if e["pooled_skill"] is not None and f["pooled_skill"] is not None:
            row["skill_difference"] = round(e["pooled_skill"] - f["pooled_skill"], 4)
            row["skill_difference_ci"] = bootstrap_difference(e["_pooled"], f["_pooled"], _skill)
        e.pop("_pooled"), f.pop("_pooled")
        rows.append(row)
    return rows


def spy_return(start: str, end: str) -> dict[str, Any] | None:
    """S&P 500 (SPY, dividends included) over the runs' window."""
    t0 = int(_at(start).timestamp()) - 5 * 86400
    t1 = min(datetime.now(UTC), _at(end))
    query = urllib.parse.urlencode(
        {
            "period1": t0,
            "period2": int(t1.timestamp()),
            "interval": "1d",
            "events": "div",
        }
    )
    try:
        data = get_json(f"https://query1.finance.yahoo.com/v8/finance/chart/SPY?{query}")
        chart = data["chart"]["result"][0]
        closes = chart["indicators"]["adjclose"][0]["adjclose"]
        stamps = chart["timestamp"]
    except (VenueError, KeyError, IndexError, TypeError):
        return None
    pairs = [(t, c) for t, c in zip(stamps, closes, strict=False) if c is not None]
    before = [c for t, c in pairs if t <= _at(start).timestamp()]
    base = before[-1] if before else pairs[0][1]
    series = [
        [datetime.fromtimestamp(t, UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), round(1000 * c / base, 2)]
        for t, c in pairs
        if t > _at(start).timestamp()
    ]
    return {"return": round(pairs[-1][1] / base - 1, 4), "series": series}


def build() -> dict[str, Any]:
    runs = [score_run(r) for r in load_runs()]
    runs.sort(key=lambda r: r["value"], reverse=True)
    start = min((r["started_at"] for r in runs), default=None)
    end = max((r["ends_at"] for r in runs), default=None)
    activity = []
    for r in runs:
        if r["kind"] != "agent":
            continue
        for t in r["trades"]:
            activity.append({"run": r["id"], "type": "trade", **t})
        for s in r["session_log"]:
            if s.get("insertions") or s.get("deletions"):
                activity.append(
                    {
                        "run": r["id"],
                        "type": "code",
                        "at": s["ended_at"],
                        "session": s["session"],
                        "files": s.get("files") or [],
                        "lines": (s.get("insertions") or 0) + (s.get("deletions") or 0),
                    }
                )
    activity.sort(key=lambda a: a["at"], reverse=True)
    arms = compare_arms(runs)
    for r in runs:
        r.pop("_scored")
    return {
        "generated_at": now_iso(),
        "benchmark": BENCHMARK_VERSION,
        "code": _commit(),
        "started_at": start,
        "runs": runs,
        "arms": arms,
        "spy": spy_return(start, end) if start else None,
        "activity": activity[:60],
        "operator_log": notes(),
    }


def _commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


def write(path) -> dict[str, Any]:
    results = build()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(results, indent=1, default=str) + "\n")
    return results
