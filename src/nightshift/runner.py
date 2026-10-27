"""Runs, sessions, and the ticker.

A run is one agent configuration trading one $1,000 account for a fixed
window. Its files live under $NIGHTSHIFT_HOME (default ~/.nightshift), which
must sit outside this repository:

    runs/<id>/run.json        what the run is (model, harness, arm, window)
    runs/<id>/ledger.db       its account, append-only
    runs/<id>/sessions.jsonl  one line per session: cost, tokens, code change
    runs/<id>/sessions/NNN.jsonl   full transcripts
    runs/<id>/history.git     the harness's snapshots of the workspace
    workspaces/<id>/          the agent's working directory, entirely its own

A session starts the run's exchange on a Unix socket, then runs Claude Code
headless in the workspace inside the OS sandbox: it can write only its
workspace, cannot read the harness, the records or other agents, and reaches
the exchange only through that socket. The harness never runs git or reads a
file inside the workspace in a way the agent could redirect.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import random
import re
import shutil
import signal
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
SYSTEM_PROMPT_LIMIT = 40_000  # characters of AGENTS.md carried into the next session
ARMS = {
    "evolving": "Everything in it persists from session to session.",
    "frozen": (
        "It is reset to its starting state at the start of every session, so nothing you write "
        "here persists; your account and its history (`ns history`) do."
    ),
}


def home() -> Path:
    return Path(os.environ.get("NIGHTSHIFT_HOME", Path.home() / ".nightshift")).resolve()


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

    def socket(self, session: int) -> Path:
        """A fresh, short path per session (Unix sockets cap near 104 bytes), outside /tmp,
        which every sandboxed agent can write."""
        digest = hashlib.sha256(f"{self.dir}:{session}".encode()).hexdigest()[:16]
        return Path.home() / ".nightshift" / "sockets" / f"{digest}.sock"

    def ledger(self) -> Ledger:
        return Ledger(self.dir / "ledger.db")

    def active(self, now: datetime | None = None) -> bool:
        return (now or datetime.now(UTC)) < _at(self.ends_at)

    def sessions(self) -> list[dict[str, Any]]:
        path = self.dir / "sessions.jsonl"
        return [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []


def _at(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


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
    if home().is_relative_to(REPO):
        raise ValueError("NIGHTSHIFT_HOME must be outside the repository agents may not read")
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
        _snapshot(run, "init", "-q")
        _commit(run, "Seed")
    return run


def _claude_version() -> str:
    out = subprocess.run(["claude", "--version"], capture_output=True, text=True, check=True)
    return "claude-code " + out.stdout.split()[0]


def _harness_commit() -> str:
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


def _seed_workspace(run: Run) -> None:
    shutil.rmtree(run.workspace, ignore_errors=True)
    shutil.copytree(AGENT / "seed", run.workspace)


# --- workspace snapshots ----------------------------------------------------


def _snapshot(run: Run, *args: str) -> str:
    """Git on the harness's own repository of the workspace, never the agent's.

    The git directory lives in the run's records, out of the agent's reach, and
    hooks, filters and user config are off, so nothing the agent writes in its
    workspace can make this command run its code.
    """
    env = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}
    command = [
        "git",
        f"--git-dir={run.dir / 'history.git'}",
        f"--work-tree={run.workspace}",
        "-c",
        "core.hooksPath=/dev/null",
        "-c",
        "core.fsmonitor=false",
        "-c",
        f"user.name={run.id}",
        "-c",
        "user.email=harness@nightshift.invalid",
        *args,
    ]
    out = subprocess.run(command, cwd=run.dir, env=env, check=True, capture_output=True, text=True)
    return out.stdout.strip()


def _commit(run: Run, message: str) -> str:
    _snapshot(run, "add", "-A")
    if _snapshot(run, "status", "--porcelain"):
        _snapshot(run, "commit", "-qm", message)
    return _snapshot(run, "rev-parse", "HEAD")


def _diff(run: Run, start: str, end: str) -> dict[str, Any]:
    rows = [
        line.split("\t") for line in _snapshot(run, "diff", "--numstat", start, end).splitlines()
    ]
    return {
        "commit": end[:12],
        "files_changed": len(rows),
        "insertions": sum(int(r[0]) for r in rows if r[0] != "-"),
        "deletions": sum(int(r[1]) for r in rows if r[1] != "-"),
        "files": [r[2] for r in rows][:50],
    }


def _system_prompt(run: Run) -> Path | None:
    """Copy the agent's AGENTS.md for Claude Code to append, refusing anything but a
    plain file in the workspace, so it cannot point the harness at another file."""
    source = run.workspace / "AGENTS.md"
    if source.is_symlink() or not source.is_file():
        return None
    if not source.resolve().is_relative_to(run.workspace.resolve()):
        return None
    text = source.read_text(errors="replace")
    if len(text) > SYSTEM_PROMPT_LIMIT:
        text = (
            text[:SYSTEM_PROMPT_LIMIT] + "\n\n[AGENTS.md was cut off here at 40,000 characters.]\n"
        )
    target = run.dir / "system-prompt.md"
    target.write_text(text)
    return target


# --- sessions ---------------------------------------------------------------


def session_settings(run: Run, others: list[Run], socket: Path) -> dict[str, Any]:
    """Claude Code settings for one session. They live outside the workspace."""
    private = [REPO, home() / "runs", home() / "logs", home() / "site", home() / "operator.jsonl"]
    private += [other.workspace for other in others if other.id != run.id]
    deny = []
    for path in private:
        pattern = f"/{path}/**" if path.suffix != ".jsonl" else f"/{path}"
        deny += [f"Read({pattern})", f"Edit({pattern})"]
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
            "network": {"allowUnixSockets": [str(socket)]},
        },
        "autoMemoryEnabled": False,
    }


def render_prompt(run: Run, session: int, now: datetime, minutes: int = 45) -> str:
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
            minutes=minutes,
        )
    )


def _install_ns() -> Path:
    """`ns` as one standalone file, because the sandbox may not read this repository."""
    bin_dir = home() / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    source = (REPO / "src" / "nightshift" / "ns.py").read_text()
    (bin_dir / "ns").write_text("#!/usr/bin/env python3\n" + source)
    (bin_dir / "ns").chmod(0o755)
    return bin_dir


def _next_session(run: Run) -> int:
    """Numbered from transcripts on disk, so a session that crashed keeps its transcript."""
    numbers = [int(p.stem) for p in (run.dir / "sessions").glob("*.jsonl") if p.stem.isdigit()]
    return max(numbers + [len(run.sessions())]) + 1


def run_session(run: Run, others: list[Run], timeout_minutes: int = 45) -> dict[str, Any] | None:
    """One headless session. Returns its record, or None if one is already running."""
    run.dir.mkdir(parents=True, exist_ok=True)
    lock = open(run.dir / "session.lock", "w")  # noqa: SIM115 - held for the session
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return None
    number = _next_session(run)
    now = datetime.now(UTC)
    if run.arm == "frozen":
        _seed_workspace(run)
        _commit(run, f"Reset to seed before session {number}")
    start_commit = _commit(run, f"Before session {number}")

    socket = run.socket(number)
    settings_path = run.dir / "settings.json"
    settings_path.write_text(json.dumps(session_settings(run, others, socket), indent=2))
    bin_dir = _install_ns()
    transcript = run.dir / "sessions" / f"{number:03d}.jsonl"
    transcript.parent.mkdir(exist_ok=True)

    command = [
        "claude",
        "-p",
        render_prompt(run, number, now, timeout_minutes),
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
    system_prompt = _system_prompt(run)
    if system_prompt:
        command += ["--append-system-prompt-file", str(system_prompt)]
    # The agent's PATH must not lead into this repository, which it may not read.
    path = [
        p for p in os.environ.get("PATH", "").split(os.pathsep) if not Path(p).is_relative_to(REPO)
    ]
    env = {
        **os.environ,
        "NS_SOCKET": str(socket),
        "PATH": os.pathsep.join([str(bin_dir), *path]),
        "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
        "DISABLE_AUTOUPDATER": "1",  # the harness must not change under a live run
    }
    env.pop("VIRTUAL_ENV", None)

    ledger = run.ledger()
    server = serve(Exchange(ledger, session=number, ends_at=run.ends_at), socket)
    timed_out, code = False, None
    try:
        with transcript.open("w") as out:
            # Its own process group, so a timeout stops every shell the agent started too.
            proc = subprocess.Popen(
                command,
                cwd=run.workspace,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=out,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            try:
                code = proc.wait(timeout=timeout_minutes * 60)
            except subprocess.TimeoutExpired:
                timed_out = True
                _stop(proc)
    finally:
        server.shutdown()
        server.server_close()
        socket.unlink(missing_ok=True)
        ledger.close()

    end_commit = _commit(run, f"Session {number}")
    record = {
        "session": number,
        "started_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ended_at": now_iso(),
        "model": run.model,
        "harness": _claude_version(),
        "exit": code,
        "timed_out": timed_out,
        **_transcript_summary(transcript, run.workspace),
        **_diff(run, start_commit, end_commit),
        "transcript": str(transcript.relative_to(run.dir)),
    }
    with (run.dir / "sessions.jsonl").open("a") as f:
        f.write(json.dumps(record) + "\n")
    lock.close()
    return record


def _stop(proc: subprocess.Popen) -> None:
    os.killpg(proc.pid, signal.SIGTERM)
    try:
        proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait()


def _transcript_summary(path: Path, workspace: Path | None = None) -> dict[str, Any]:
    """Cost, tokens, turns, and the closing summary from Claude Code's result line."""
    own = str(workspace) if workspace else None
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
            for c in calls:
                text = json.dumps(c.get("input"))
                tmp_refs += bool(SHARED_TMP.search(text.replace(own, "") if own else text))
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
    still holds then is worth the bid. Forecasts keep resolving afterwards. One
    run's failure is reported and does not stop the others.
    """
    cache: dict = {}
    report: dict[str, Any] = {}
    for run in load_runs():
        try:
            report[run.id] = _tick_run(run, cache)
        except Exception as exc:
            report[run.id] = {"error": f"{type(exc).__name__}: {exc}"}
    return report


def _tick_run(run: Run, cache: dict) -> dict[str, Any]:
    ledger = run.ledger()
    exchange = Exchange(ledger, ends_at=run.ends_at)
    try:
        marks = ledger.events("mark")
        final = bool(not run.active() and marks and marks[-1]["at"] >= run.ends_at)
        if run.kind == "baseline" and run.active() and _due(run.dir / "last_trade", hours=1):
            rng = random.Random(f"{run.id}:{now_iso()[:13]}")
            baselines.STRATEGIES[run.strategy or ""](exchange, rng)
            (run.dir / "last_trade").write_text(now_iso())
        settled, value = [], marks[-1]["value"] if marks else run.cash
        if not final:
            result = exchange.settle_and_mark(cache)
            settled, value = result["settled"], result["mark"]["value"]
        sweep = _due(run.dir / "last_sweep", hours=24)
        resolved = exchange.resolve_forecasts(cache, everything=sweep)
        if sweep:
            (run.dir / "last_sweep").write_text(now_iso())
        return {
            "value": Decimal(value).quantize(Decimal("0.01")),
            "settled": len(settled),
            "resolved": len(resolved),
            "final": final,
        }
    finally:
        ledger.close()


def _due(stamp: Path, hours: float) -> bool:
    if not stamp.exists():
        return True
    elapsed = datetime.now(UTC) - _at(stamp.read_text().strip())
    return elapsed >= timedelta(hours=hours) - timedelta(minutes=5)
