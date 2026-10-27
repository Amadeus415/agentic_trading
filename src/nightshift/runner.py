"""Runs, sessions, and the ticker.

A run is one agent configuration trading one $1,000 account for a fixed
window. Its files live under $NIGHTSHIFT_HOME (default ./var):

    runs/<id>/run.json        what the run is (model, harness, arm, window)
    runs/<id>/ledger.db       its account, append-only
    runs/<id>/sessions.jsonl  one line per session: cost, tokens, code change
    runs/<id>/sessions/NNN.jsonl   full transcripts
    workspaces/<id>/          the agent's own git repository, and its cwd

A session starts the run's exchange on a Unix socket, then runs Claude Code
headless in the workspace inside the OS sandbox: it can write only its
workspace, read nothing of the benchmark's records or other agents, and reach
the exchange only through that socket.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import random
import re
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from nightshift import BENCHMARK_VERSION, baselines
from nightshift.exchange import Exchange, serve
from nightshift.ledger import Ledger, now_iso

REPO = Path(__file__).resolve().parents[2]
AGENT = REPO / "agent"
TOOLS = "Bash,Read,Edit,Write,Glob,Grep,WebSearch,WebFetch,Agent"
SHARED_TMP = re.compile(r"(?<![\w.])/(private/)?tmp/|/var/folders/")
ARMS = {
    "evolving": "Everything in it persists from session to session.",
    "frozen": (
        "It is reset to its starting state at the start of every session, so nothing you write "
        "here persists; your account and its history (`ns history`) do."
    ),
}


def home() -> Path:
    return Path(os.environ.get("NIGHTSHIFT_HOME", REPO / "var")).resolve()


@dataclass
class Run:
    id: str
    kind: str  # "agent" or "baseline"
    started_at: str
    ends_at: str
    cash: str = "1000"
    model: str | None = None
    harness: str | None = None
    arm: str | None = None  # agents: "evolving" or "frozen"
    strategy: str | None = None  # baselines: a name in baselines.STRATEGIES
    benchmark: str = BENCHMARK_VERSION
    code: str = ""  # the harness commit the run started on

    @property
    def dir(self) -> Path:
        return home() / "runs" / self.id

    @property
    def workspace(self) -> Path:
        return home() / "workspaces" / self.id

    @property
    def socket(self) -> Path:
        # Unix socket paths are capped near 104 bytes, so keep this one short. It sits
        # outside /tmp, which the sandbox lets every agent write, so no agent can remove it.
        digest = hashlib.sha256(str(self.dir).encode()).hexdigest()[:16]
        return Path.home() / ".nightshift" / f"{digest}.sock"

    def ledger(self) -> Ledger:
        return Ledger(self.dir / "ledger.db")

    def active(self, now: datetime | None = None) -> bool:
        return (now or datetime.now(UTC)) < _at(self.ends_at)

    def sessions(self) -> list[dict[str, Any]]:
        path = self.dir / "sessions.jsonl"
        return [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []


def _at(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def load_runs() -> list[Run]:
    root = home() / "runs"
    if not root.exists():
        return []
    return [Run(**json.loads(p.read_text())) for p in sorted(root.glob("*/run.json"))]


def create_run(
    run_id: str,
    *,
    model: str | None = None,
    arm: str | None = None,
    strategy: str | None = None,
    days: int = 28,
    start: datetime | None = None,
) -> Run:
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{0,63}", run_id):
        raise ValueError("run IDs are lowercase letters, digits, dots and dashes")
    if (model is None) == (strategy is None):
        raise ValueError("a run is either an agent (model and arm) or a baseline (strategy)")
    if model and arm not in ARMS:
        raise ValueError(f"arm must be one of {', '.join(ARMS)}")
    if strategy and strategy not in baselines.STRATEGIES:
        raise ValueError(f"strategy must be one of {', '.join(baselines.STRATEGIES)}")
    start = start or datetime.now(UTC)
    run = Run(
        id=run_id,
        kind="agent" if model else "baseline",
        started_at=start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        ends_at=(start + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        model=model,
        harness=_claude_version() if model else None,
        arm=arm,
        strategy=strategy,
        code=_harness_commit(),
    )
    run.dir.mkdir(parents=True, exist_ok=False)
    (run.dir / "run.json").write_text(json.dumps(asdict(run), indent=2) + "\n")
    ledger = run.ledger()
    ledger.append("open", {"cash": run.cash, "run": run.id})
    ledger.close()
    if run.kind == "agent":
        _seed_workspace(run)
    return run


def _claude_version() -> str:
    out = subprocess.run(["claude", "--version"], capture_output=True, text=True, check=True)
    return "claude-code " + out.stdout.split()[0]


def _harness_commit() -> str:
    try:
        return _git(REPO, "rev-parse", "--short", "HEAD")
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


def _seed_workspace(run: Run) -> None:
    shutil.rmtree(run.workspace, ignore_errors=True)
    shutil.copytree(AGENT / "seed", run.workspace)
    _git(run.workspace, "init", "-q", "-b", "main")
    _git(run.workspace, "config", "user.name", run.id)
    _git(run.workspace, "config", "user.email", f"{run.id}@nightshift.invalid")
    _git(run.workspace, "add", "-A")
    _git(run.workspace, "commit", "-qm", "Seed workspace")


# --- sessions ---------------------------------------------------------------


def session_settings(run: Run, others: list[Run]) -> dict[str, Any]:
    """Claude Code settings for one session. They live outside the workspace."""
    records = home() / "runs"
    deny = [f"Read(/{records}/**)", f"Edit(/{records}/**)", f"Read(/{home() / 'site'}/**)"]
    for other in others:
        if other.id != run.id:
            deny += [f"Read(/{other.workspace}/**)", f"Edit(/{other.workspace}/**)"]
    return {
        "permissions": {
            "allow": [
                "Bash",
                "Read",
                "Glob",
                "Grep",
                "WebSearch",
                "WebFetch",
                "Agent",
                f"Edit(/{run.workspace}/**)",
                f"Write(/{run.workspace}/**)",
            ],
            "deny": deny,
        },
        "sandbox": {
            "enabled": True,
            "autoAllowBashIfSandboxed": True,
            "allowUnsandboxedCommands": False,
            "network": {"allowUnixSockets": [str(run.socket)]},
        },
        "autoMemoryEnabled": False,
    }


def render_prompt(run: Run, session: int, now: datetime) -> str:
    start, end = _at(run.started_at), _at(run.ends_at)
    return (
        (AGENT / "PROMPT.md")
        .read_text()
        .format(
            session=session,
            now=now.strftime("%A %Y-%m-%d %H:%M UTC"),
            day=(now - start).days + 1,
            days=(end - start).days,
            ends=end.strftime("%Y-%m-%d %H:%M UTC"),
            workspace_rule=ARMS[run.arm or "evolving"],
        )
    )


def run_session(run: Run, others: list[Run], timeout_minutes: int = 45) -> dict[str, Any] | None:
    """One headless session. Returns its record, or None if one is already running."""
    run.dir.mkdir(parents=True, exist_ok=True)
    lock = open(run.dir / "session.lock", "w")  # noqa: SIM115 - held for the session
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return None
    number = len(run.sessions()) + 1
    now = datetime.now(UTC)
    if run.arm == "frozen":
        _seed_workspace(run)
    start_commit = _git(run.workspace, "rev-parse", "HEAD")

    settings_path = run.dir / "settings.json"
    settings_path.write_text(json.dumps(session_settings(run, others), indent=2))
    bin_dir = home() / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    ns = bin_dir / "ns"
    if not ns.exists():
        ns.symlink_to(Path(shutil.which("ns") or REPO / ".venv/bin/ns"))
    run.socket.parent.mkdir(parents=True, exist_ok=True)
    transcript = run.dir / "sessions" / f"{number:03d}.jsonl"
    transcript.parent.mkdir(exist_ok=True)

    command = [
        "claude",
        "-p",
        render_prompt(run, number, now),
        "--model",
        run.model or "",
        "--settings",
        str(settings_path),
        "--setting-sources",
        "",
        "--permission-mode",
        "dontAsk",
        "--strict-mcp-config",
        "--disable-slash-commands",
        "--tools",
        TOOLS,
        "--no-session-persistence",
        "--output-format",
        "stream-json",
        "--verbose",
    ]
    if (run.workspace / "AGENTS.md").exists():
        command += ["--append-system-prompt-file", str(run.workspace / "AGENTS.md")]
    env = {
        **os.environ,
        "NS_SOCKET": str(run.socket),
        "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
        "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
        "DISABLE_AUTOUPDATER": "1",  # the harness must not change under a live run
    }

    ledger = run.ledger()
    server = serve(Exchange(ledger, session=number), run.socket)
    timed_out, code = False, None
    try:
        with transcript.open("w") as out:
            proc = subprocess.run(
                command,
                cwd=run.workspace,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=out,
                stderr=subprocess.STDOUT,
                timeout=timeout_minutes * 60,
            )
            code = proc.returncode
    except subprocess.TimeoutExpired:
        timed_out = True
    finally:
        server.shutdown()
        server.server_close()
        run.socket.unlink(missing_ok=True)
        ledger.close()

    record = {
        "session": number,
        "started_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ended_at": now_iso(),
        "model": run.model,
        "harness": _claude_version(),
        "exit": code,
        "timed_out": timed_out,
        **_transcript_summary(transcript),
        **_commit_workspace(run, number, start_commit),
        "transcript": str(transcript.relative_to(run.dir)),
    }
    with (run.dir / "sessions.jsonl").open("a") as f:
        f.write(json.dumps(record) + "\n")
    lock.close()
    return record


def _transcript_summary(path: Path) -> dict[str, Any]:
    """Cost, tokens, turns, and the closing summary from Claude Code's result line."""
    result: dict[str, Any] = {}
    tools = tmp_refs = 0
    for line in path.read_text(errors="replace").splitlines():
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if msg.get("type") == "assistant":
            content = (msg.get("message") or {}).get("content") or []
            calls = [c for c in content if c.get("type") == "tool_use"]
            tools += len(calls)
            tmp_refs += sum(1 for c in calls if SHARED_TMP.search(json.dumps(c.get("input"))))
        elif msg.get("type") == "result":
            result = msg
    usage = result.get("usage") or {}
    return {
        "cost_usd": result.get("total_cost_usd"),
        "turns": result.get("num_turns"),
        "tool_calls": tools,
        "input_tokens": usage.get("input_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "cache_read_tokens": usage.get("cache_read_input_tokens"),
        "cache_write_tokens": usage.get("cache_creation_input_tokens"),
        "is_error": result.get("is_error"),
        # Tool calls the permission rules refused: the first place to look for tampering.
        "denials": len(result.get("permission_denials") or []),
        # The sandbox must leave /tmp writable, so a frozen agent could hide notes there.
        "tmp_refs": tmp_refs,
        "summary": (result.get("result") or "")[:4000],
    }


def _commit_workspace(run: Run, number: int, start: str) -> dict[str, Any]:
    ws = run.workspace
    _git(ws, "add", "-A")
    if _git(ws, "status", "--porcelain"):
        _git(ws, "commit", "-qm", f"Session {number}: uncommitted changes")
    end = _git(ws, "rev-parse", "HEAD")
    rows = [line.split("\t") for line in _git(ws, "diff", "--numstat", start, end).splitlines()]
    messages = _git(ws, "log", "--format=%s", f"{start}..{end}").splitlines()
    return {
        "commit": end[:12],
        "files_changed": len(rows),
        "insertions": sum(int(r[0]) for r in rows if r[0] != "-"),
        "deletions": sum(int(r[1]) for r in rows if r[1] != "-"),
        "commit_messages": list(reversed(messages)),
    }


def run_sessions(timeout_minutes: int = 45) -> list[dict[str, Any] | None]:
    """One session for every active agent run, all at once so they face the same market."""
    runs = load_runs()
    agents = [r for r in runs if r.kind == "agent" and r.active()]
    if not agents:
        return []
    with ThreadPoolExecutor(len(agents)) as pool:
        return list(pool.map(lambda r: run_session(r, runs, timeout_minutes), agents))


# --- the operator's log -----------------------------------------------------


def note(text: str) -> dict[str, Any]:
    """Record a human intervention (a restart, a fix, a pause) so results can disclose it."""
    entry = {"at": now_iso(), "text": text}
    home().mkdir(parents=True, exist_ok=True)
    with (home() / "operator.jsonl").open("a") as f:
        f.write(json.dumps(entry) + "\n")
    return entry


def notes() -> list[dict[str, Any]]:
    path = home() / "operator.jsonl"
    return [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []


# --- the ticker -------------------------------------------------------------


def tick() -> dict[str, Any]:
    """Settle, mark, and resolve every run; let baselines trade once an hour.

    A run's money stops at its first valuation after the window ends: what it
    still holds then is worth the bid. Forecasts keep resolving afterwards.
    """
    cache: dict = {}
    report = {}
    for run in load_runs():
        ledger = run.ledger()
        exchange = Exchange(ledger)
        try:
            marks = ledger.events("mark")
            closed = not run.active() and marks and marks[-1]["at"] >= run.ends_at
            if run.kind == "baseline" and run.active() and _due(run, hours=1):
                rng = random.Random(f"{run.id}:{now_iso()[:13]}")
                baselines.STRATEGIES[run.strategy or ""](exchange, rng)
                (run.dir / "last_trade").write_text(now_iso())
            settled, value = [], marks[-1]["value"] if marks else run.cash
            if not closed:
                result = exchange.settle_and_mark(cache)
                settled, value = result["settled"], result["mark"]["value"]
            report[run.id] = {
                "value": Decimal(value).quantize(Decimal("0.01")),
                "settled": len(settled),
                "resolved": len(exchange.resolve_forecasts(cache)),
                "final": bool(closed),
            }
        finally:
            ledger.close()
    return report


def _due(run: Run, hours: float) -> bool:
    path = run.dir / "last_trade"
    if not path.exists():
        return True
    return datetime.now(UTC) - _at(path.read_text().strip()) >= timedelta(hours=hours) - timedelta(
        minutes=5
    )
