"""`nightshift`: the operator's commands. Agents never see these."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from nightshift import runner, score, site
from nightshift.exchange import dumps


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="nightshift", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("new", help="create a run: an agent (--model, --arm) or a baseline")
    p.add_argument("id")
    p.add_argument("--model", help="Claude model ID, e.g. claude-opus-5-5")
    p.add_argument("--arm", choices=sorted(runner.ARMS))
    p.add_argument("--baseline", dest="strategy", help="favorites or random")
    p.add_argument("--days", type=int, default=28)

    p = sub.add_parser("session", help="one session for every live agent run, in parallel")
    p.add_argument("--run", help="only this run")
    p.add_argument("--timeout", type=int, default=45, help="minutes")

    sub.add_parser("tick", help="settle, mark, resolve forecasts, and trade baselines")
    sub.add_parser("verify", help="check every ledger's hash chain")
    p = sub.add_parser("note", help="log a human intervention; it is published with the results")
    p.add_argument("text")
    sub.add_parser("runs", help="list runs")

    p = sub.add_parser("publish", help="score every run and build the website")
    p.add_argument("--out", type=Path, help="site directory (default $NIGHTSHIFT_HOME/site)")

    args = parser.parse_args(argv)
    if args.command == "new":
        run = runner.create_run(
            args.id, model=args.model, arm=args.arm, strategy=args.strategy, days=args.days
        )
        print(json.dumps(runner.asdict(run), indent=1))
    elif args.command == "session":
        runs = runner.load_runs()
        if args.run:
            match = [r for r in runs if r.id == args.run]
            if not match:
                parser.error(f"no run {args.run}")
            records = [runner.run_session(match[0], runs, args.timeout)]
        else:
            records = runner.run_sessions(args.timeout)
        for record in records:
            if record:
                print(dumps({k: v for k, v in record.items() if k != "summary"}))
    elif args.command == "tick":
        print(dumps(runner.tick(), indent=1))
    elif args.command == "verify":
        for run in runner.load_runs():
            ledger = run.ledger()
            try:
                print(f"{run.id}: {ledger.verify()} events, chain intact")
            finally:
                ledger.close()
    elif args.command == "note":
        print(json.dumps(runner.note(args.text)))
    elif args.command == "runs":
        for run in runner.load_runs():
            what = f"{run.model} {run.arm}" if run.kind == "agent" else f"baseline {run.strategy}"
            state = "live" if run.active() else "finished"
            print(f"{run.id:32} {what:36} {state:9} ends {run.ends_at}")
    elif args.command == "publish":
        out = args.out or runner.home() / "site"
        results = score.write(out / "data.json")
        site.build(results, out)
        print(f"{len(results['runs'])} runs -> {out / 'index.html'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
