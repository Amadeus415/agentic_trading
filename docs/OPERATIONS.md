# Operations

How to run the benchmark on one Mac with a Claude Max subscription.

## Use a pinned checkout

The harness must not change under a live run. Run from a separate clone checked out at a release tag, and develop in this one:

```bash
git clone https://github.com/Amadeus415/agentic_trading.git ../nightshift-runtime
cd ../nightshift-runtime && git checkout v0.1.0 && make install
```

Every run records the harness commit it started on, and every session records its Claude Code version.

## The v1 lineup

Two replicates of each arm on the strongest model, plus the code-only baselines, all started at the same moment:

```bash
for n in 1 2; do
  uv run nightshift new opus-evolving-$n --model claude-opus-5-5 --arm evolving
  uv run nightshift new opus-frozen-$n   --model claude-opus-5-5 --arm frozen
done
uv run nightshift new favorites --baseline favorites
uv run nightshift new random    --baseline random
```

This is four Opus sessions at a time, four times a day. If the subscription has room, add a `claude-sonnet-5-5` pair to see how the effect varies with model strength. Adding runs later is fine; they start their own 28-day window and are compared with runs that overlap it.

## Schedule

```bash
./scripts/install_schedule.sh
```

This installs two LaunchAgents that read `NIGHTSHIFT_HOME` (default `./var`):

| Job | When | What |
| --- | --- | --- |
| `com.nightshift.session` | 00:15, 06:15, 12:15, 18:15 local | `nightshift session`: one session per live agent, in parallel |
| `com.nightshift.tick` | every 15 minutes | `nightshift tick && nightshift publish`: settle, value at the bid, trade baselines, rebuild the site |

The jobs run only while the Mac is awake; after sleep, launchd runs one missed session. Logs are in `$NIGHTSHIFT_HOME/logs/`. To run a session now: `launchctl kickstart gui/$UID/com.nightshift.session`.

The pilot's jobs (`com.edgecraft.*`) must be removed so they stop calling a model:

```bash
for job in research review monitor dashboard; do
  launchctl bootout gui/$UID/com.edgecraft.$job 2>/dev/null
  launchctl bootout gui/$UID/com.edgecraft.paper-$job 2>/dev/null
done
rm -f ~/Library/LaunchAgents/com.edgecraft.*.plist
```

## Daily checks

```bash
uv run nightshift runs      # what is live
uv run nightshift verify    # every ledger's hash chain
make site                   # rebuild and open the site
```

Each session line in `runs/<id>/sessions.jsonl` has its cost, tokens, tool calls, lines changed, timeout flag and `denials`, the number of tool calls the permission rules refused. A non-zero `denials` count means read that transcript (`runs/<id>/sessions/NNN.jsonl`).

## Interventions

Log every human action while runs are live, before or right after doing it:

```bash
uv run nightshift note "Restarted the tick job after a Kalshi API outage, 14:00-15:10 UTC."
```

Notes are published on the site. Never edit an agent's workspace, prompt or ledger by hand. If the harness has a bug that changes outcomes, fix it in a new benchmark version and start new runs; don't patch a live one.

## Publishing

`nightshift publish` writes `$NIGHTSHIFT_HOME/site/` (static HTML plus `data.json`). Host it anywhere static: GitHub Pages, Cloudflare Pages, or an `rsync` to a bucket. Transcripts stay private in `runs/`; publish them separately once a run ends, after a read for anything sensitive.
