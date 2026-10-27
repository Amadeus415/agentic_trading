import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from nightshift import runner, score, site
from nightshift.exchange import Exchange


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("NIGHTSHIFT_HOME", str(tmp_path))
    monkeypatch.setattr(runner, "_claude_version", lambda: "claude-code test")
    monkeypatch.setattr(score, "spy_return", lambda start, end: None)
    return tmp_path


def test_agent_runs_get_a_seeded_workspace_and_a_private_history(home):
    run = runner.create_run("a1", model="claude-test", arm="evolving", days=7)
    assert (run.workspace / "AGENTS.md").exists()
    assert not (run.workspace / ".git").exists()  # the snapshots live in the records
    assert runner._snapshot(run, "log", "--format=%s") == "Seed"
    assert run.ledger().account().cash == 1000
    assert [r.id for r in runner.load_runs()] == ["a1"]
    with pytest.raises(ValueError):
        runner.create_run("bad", model="m", arm="sometimes")
    with pytest.raises(ValueError):
        runner.create_run("bad2", strategy="nonsense")
    with pytest.raises(ValueError, match="run IDs"):
        runner.create_run("../escape", strategy="favorites")


def test_state_must_live_outside_the_repository(monkeypatch):
    monkeypatch.setenv("NIGHTSHIFT_HOME", str(runner.REPO / "var"))
    with pytest.raises(ValueError, match="outside the repository"):
        runner.create_run("x", strategy="favorites")


def test_session_settings_fence_the_agent_into_its_workspace(home):
    me = runner.create_run("me", model="m", arm="evolving")
    other = runner.create_run("other", model="m", arm="frozen")
    socket = me.socket(3)
    settings = runner.session_settings(me, [me, other], socket)
    deny, allow = settings["permissions"]["deny"], settings["permissions"]["allow"]
    for private in (runner.REPO, home / "runs", home / "logs", home / "site", other.workspace):
        assert f"Read(/{private}/**)" in deny and f"Edit(/{private}/**)" in deny
    assert f"Read(/{home / 'operator.jsonl'})" in deny
    assert not any(str(me.workspace) in rule for rule in deny)
    assert f"Edit(/{me.workspace}/**)" in allow and "Edit" not in allow
    sandbox = settings["sandbox"]
    assert sandbox["enabled"] and not sandbox["allowUnsandboxedCommands"]
    assert sandbox["network"]["allowUnixSockets"] == [str(socket)]
    assert len(str(socket)) < 100 and socket.parent == Path.home() / ".nightshift" / "sockets"
    assert me.socket(4) != socket


def test_prompt_tells_each_arm_what_persists(home):
    evolving = runner.create_run("e", model="m", arm="evolving", days=28)
    frozen = runner.create_run("f", model="m", arm="frozen", days=28)
    now = datetime.now(UTC)
    text = runner.render_prompt(evolving, 3, now)
    assert "session 3" in text and "day 1 of 28" in text and "persists from session" in text
    assert "up to 45 minutes" in text
    assert "reset to its starting state" in runner.render_prompt(frozen, 1, now)


def test_snapshots_count_what_the_agent_changed_and_ignore_its_own_git(home):
    run = runner.create_run("c", model="m", arm="evolving")
    start = runner._commit(run, "Before session 1")
    (run.workspace / "tool.py").write_text("print('hi')\n")
    (run.workspace / "notes.md").write_text("a\nb\n")
    (run.workspace / ".git").mkdir()  # an agent may keep its own repository
    (run.workspace / ".git" / "config").write_text("[core]\n\thooksPath = /evil\n")
    end = runner._commit(run, "Session 1")
    info = runner._diff(run, start, end)
    assert info["files_changed"] == 2 and info["insertions"] == 3
    assert sorted(info["files"]) == ["notes.md", "tool.py"]


def test_system_prompt_is_a_copy_and_refuses_symlinks(home):
    run = runner.create_run("s", model="m", arm="evolving")
    copy = runner._system_prompt(run)
    assert copy and copy.parent == run.dir and "My instructions" in copy.read_text()
    (run.workspace / "AGENTS.md").unlink()
    (run.workspace / "AGENTS.md").symlink_to(home / "runs" / "s" / "run.json")
    assert runner._system_prompt(run) is None
    (run.workspace / "AGENTS.md").unlink()
    (run.workspace / "AGENTS.md").write_text("x" * (runner.SYSTEM_PROMPT_LIMIT + 10))
    assert "cut off" in runner._system_prompt(run).read_text()


def test_ns_is_installed_as_one_standalone_file(home):
    bin_dir = runner._install_ns()
    script = (bin_dir / "ns").read_text()
    assert script.startswith("#!/usr/bin/env python3") and "from nightshift" not in script


def test_crashed_sessions_keep_their_transcripts(home):
    run = runner.create_run("n", model="m", arm="evolving")
    (run.dir / "sessions").mkdir()
    (run.dir / "sessions" / "001.jsonl").write_text("")
    assert runner._next_session(run) == 2


def test_transcript_summary_reads_cost_tool_calls_and_tmp_use(tmp_path):
    path = tmp_path / "t.jsonl"
    lines = [
        {
            "type": "assistant",
            "message": {"content": [{"type": "tool_use", "input": {"file": "/tmp/me/AGENTS.md"}}]},
        },
        {
            "type": "assistant",
            "message": {"content": [{"type": "tool_use", "input": {"command": "cat /tmp/x"}}]},
        },
        {
            "type": "result",
            "total_cost_usd": 1.25,
            "num_turns": 4,
            "result": "done",
            "usage": {"output_tokens": 99},
            "permission_denials": [{"tool_name": "Read"}],
        },
    ]
    path.write_text("\n".join(json.dumps(x) for x in lines) + "\nnot json\n")
    summary = runner._transcript_summary(path, Path("/tmp/me"))
    assert summary["cost_usd"] == 1.25 and summary["tool_calls"] == 2
    assert summary["output_tokens"] == 99 and summary["summary"] == "done"
    assert summary["tmp_refs"] == 1 and summary["denials"] == 1


def fill(market, event, p_yes, market_yes, cash="-5.1", **extra):
    return {
        "market": market,
        "event": event,
        "outcome": "YES",
        "side": "buy",
        "shares": "10",
        "price": "0.5",
        "fee": "0.1",
        "cash": cash,
        "p_yes": str(p_yes),
        "market_yes": str(market_yes),
        "question": "Will <script> run?",
        "note": "a & b",
        **extra,
    }


def test_publish_builds_pages_for_every_run(home):
    run = runner.create_run("pub-1", model="claude-test", arm="evolving")
    ledger = run.ledger()
    ledger.append("fill", fill("kalshi:X", "E", 0.6, 0.5))
    ledger.append("mark", {"cash": "990", "value": "1012.5", "positions": []})
    runner.create_run("fav", strategy="favorites")
    results = score.write(home / "site" / "data.json")
    site.build(results, home / "site")
    index = (home / "site" / "index.html").read_text()
    assert "Will &lt;script&gt; run?" in index and "<script>" not in index
    assert "$1,012.50" in index and "Favorites baseline" in index
    assert (home / "site" / "runs" / "fav.html").exists()
    assert results["runs"][0]["return"] == 0.0125
    assert "_scored" not in json.dumps(results)


def test_scores_and_intervals_from_a_ledger(home):
    run = runner.create_run("scored", model="claude-test", arm="evolving")
    ledger = run.ledger()
    for i, (p_yes, market_yes, payout) in enumerate([(0.9, 0.6, 1), (0.2, 0.5, 0), (0.7, 0.8, 1)]):
        market = f"kalshi:M{i}"
        ledger.append("fill", fill(market, f"E{i}", p_yes, market_yes))
        ledger.append(
            "settle", {"market": market, "outcome": "YES", "shares": "10", "cash": str(10 * payout)}
        )
        ledger.append("resolve", {"market": market, "payout_yes": str(payout)})
    ledger.append("mark", {"cash": "1004.7", "value": "1004.7", "positions": []})
    ledger.close()
    r = score.score_run(run)
    assert r["closed_positions"] == 3 and r["wins"] == 2
    assert r["edge"] == round((20 - 15.3) / 15.3, 4)
    assert r["brier"] == round((0.01 + 0.04 + 0.09) / 3, 4)
    assert r["skill"] > 0 and r["skill_ci"] and r["edge_ci"]
    results = score.write(home / "site" / "data.json")
    site.build(results, home / "site")
    assert 'class="ci">[' in (home / "site" / "index.html").read_text()


def test_finished_runs_count_open_positions_at_their_final_mark(home):
    start = datetime.now(UTC) - timedelta(days=8)
    run = runner.create_run("done", model="m", arm="evolving", days=7, start=start)
    ledger = run.ledger()
    ledger.append("fill", fill("kalshi:W", "E1", 0.9, 0.5, cash="-5"))
    ledger.append("fill", {**fill("kalshi:W", "E1", 0.9, 0.5, cash="9"), "side": "sell"})
    ledger.append("fill", fill("kalshi:L", "E2", 0.9, 0.5, cash="-5"))
    position = [{"market": "kalshi:L", "outcome": "YES", "shares": "10", "price": "0.05"}]
    ledger.append("mark", {"cash": "999", "value": "999.5", "positions": position})
    ledger.close()
    r = score.score_run(run)
    # Selling the winner and holding the loser past the window still counts the loser.
    assert r["closed_positions"] == 2
    assert r["edge"] == round((4 + (-5 + 0.5)) / 10, 4)


def test_money_stops_at_the_first_mark_after_the_window(home, monkeypatch):
    marked = []
    monkeypatch.setattr(
        Exchange,
        "settle_and_mark",
        lambda self, cache: (
            marked.append(1)
            or {"settled": [], "mark": self.ledger.append("mark", {"value": "1000"})}
        ),
    )
    monkeypatch.setattr(Exchange, "resolve_forecasts", lambda self, cache, everything: [])
    start = datetime.now(UTC) - timedelta(days=8)
    runner.create_run("ended", model="m", arm="evolving", days=7, start=start)
    assert runner.tick()["ended"]["final"] is False
    assert runner.tick()["ended"]["final"] is True
    assert len(marked) == 1


def test_one_failing_run_does_not_stop_the_ticker(home, monkeypatch):
    runner.create_run("a", strategy="favorites")
    runner.create_run("b", strategy="random")
    calls = []

    def flaky(self, cache):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("venue down")
        return {"settled": [], "mark": self.ledger.append("mark", {"value": "1000"})}

    monkeypatch.setattr(Exchange, "settle_and_mark", flaky)
    monkeypatch.setattr(Exchange, "resolve_forecasts", lambda self, cache, everything: [])
    monkeypatch.setattr(runner, "_due", lambda stamp, hours: False)
    report = runner.tick()
    assert "venue down" in report["a"]["error"] and report["b"]["value"] == 1000
