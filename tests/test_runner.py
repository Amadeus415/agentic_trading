import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from nightshift import runner, score, site


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("NIGHTSHIFT_HOME", str(tmp_path))
    monkeypatch.setattr(runner, "_claude_version", lambda: "claude-code test")
    return tmp_path


def test_agent_runs_get_a_seeded_git_workspace(home):
    run = runner.create_run("a1", model="claude-test", arm="evolving", days=7)
    assert (run.workspace / "AGENTS.md").exists()
    assert runner._git(run.workspace, "log", "--format=%s") == "Seed workspace"
    assert run.ledger().account().cash == 1000
    assert [r.id for r in runner.load_runs()] == ["a1"]
    with pytest.raises(ValueError):
        runner.create_run("bad", model="m", arm="sometimes")
    with pytest.raises(ValueError):
        runner.create_run("bad2", strategy="nonsense")
    with pytest.raises(ValueError, match="run IDs"):
        runner.create_run("../escape", strategy="favorites")


def test_session_settings_fence_the_agent_into_its_workspace(home):
    me = runner.create_run("me", model="m", arm="evolving")
    other = runner.create_run("other", model="m", arm="frozen")
    settings = runner.session_settings(me, [me, other])
    deny, allow = settings["permissions"]["deny"], settings["permissions"]["allow"]
    assert f"Read(/{home / 'runs'}/**)" in deny and f"Edit(/{home / 'runs'}/**)" in deny
    assert f"Read(/{other.workspace}/**)" in deny
    assert f"Read(/{me.workspace}/**)" not in deny
    assert f"Edit(/{me.workspace}/**)" in allow and "Edit" not in allow
    sandbox = settings["sandbox"]
    assert sandbox["enabled"] and not sandbox["allowUnsandboxedCommands"]
    assert sandbox["network"]["allowUnixSockets"] == [str(me.socket)]
    assert len(str(me.socket)) < 100 and me.socket.parent == Path.home() / ".nightshift"


def test_prompt_tells_each_arm_what_persists(home):
    evolving = runner.create_run("e", model="m", arm="evolving", days=28)
    frozen = runner.create_run("f", model="m", arm="frozen", days=28)
    now = datetime.now(UTC)
    text = runner.render_prompt(evolving, 3, now)
    assert "session 3" in text and "day 1 of 28" in text and "persists from session" in text
    assert "reset to its starting state" in runner.render_prompt(frozen, 1, now)


def test_commit_records_what_the_agent_changed(home):
    run = runner.create_run("c", model="m", arm="evolving")
    start = runner._git(run.workspace, "rev-parse", "HEAD")
    (run.workspace / "tool.py").write_text("print('hi')\n")
    runner._git(run.workspace, "add", "-A")
    runner._git(run.workspace, "commit", "-qm", "Add a tool because scanning by hand is slow")
    (run.workspace / "notes.md").write_text("a\nb\n")
    info = runner._commit_workspace(run, 1, start)
    assert info["files_changed"] == 2 and info["insertions"] == 3
    assert info["commit_messages"] == [
        "Add a tool because scanning by hand is slow",
        "Session 1: uncommitted changes",
    ]


def test_transcript_summary_reads_cost_and_tool_calls(tmp_path):
    path = tmp_path / "t.jsonl"
    lines = [
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "input": {}}]}},
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
        },
    ]
    path.write_text("\n".join(json.dumps(x) for x in lines) + "\nnot json\n")
    summary = runner._transcript_summary(path)
    assert summary["cost_usd"] == 1.25 and summary["tool_calls"] == 2
    assert summary["tmp_refs"] == 1
    assert summary["output_tokens"] == 99 and summary["summary"] == "done"


def test_publish_builds_pages_for_every_run(home, monkeypatch):
    monkeypatch.setattr(score, "spy_return", lambda start: None)
    run = runner.create_run("pub-1", model="claude-test", arm="evolving")
    ledger = run.ledger()
    ledger.append(
        "fill",
        {
            "market": "kalshi:X",
            "outcome": "YES",
            "side": "buy",
            "shares": "1",
            "price": "0.5",
            "fee": "0",
            "cash": "-0.5",
            "p_yes": "0.6",
            "question": "Will <script> run?",
            "note": "a & b",
        },
    )
    ledger.append("mark", {"cash": "990", "value": "1012.5", "positions": []})
    runner.create_run("fav", strategy="favorites")
    results = score.write(home / "site" / "data.json")
    site.build(results, home / "site")
    index = (home / "site" / "index.html").read_text()
    assert "Will &lt;script&gt; run?" in index and "<script>" not in index
    assert "$1,012.50" in index and "Favorites baseline" in index
    assert (home / "site" / "runs" / "fav.html").exists()
    assert results["runs"][0]["return"] == 0.0125


def test_scores_and_intervals_from_a_ledger(home, monkeypatch):
    monkeypatch.setattr(score, "spy_return", lambda start: None)
    run = runner.create_run("scored", model="claude-test", arm="evolving")
    ledger = run.ledger()
    for i, (p_yes, market_yes, payout) in enumerate([(0.9, 0.6, 1), (0.2, 0.5, 0), (0.7, 0.8, 1)]):
        market = f"kalshi:M{i}"
        ledger.append(
            "fill",
            {
                "market": market,
                "event": f"E{i}",
                "outcome": "YES",
                "side": "buy",
                "shares": "10",
                "price": "0.5",
                "fee": "0.1",
                "cash": "-5.1",
                "p_yes": str(p_yes),
                "market_yes": str(market_yes),
                "question": "Q",
            },
        )
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


def test_money_stops_at_the_first_mark_after_the_window(home, monkeypatch):
    from datetime import timedelta

    from nightshift.exchange import Exchange

    marked = []
    monkeypatch.setattr(
        Exchange,
        "settle_and_mark",
        lambda self, cache: (
            marked.append(1)
            or {"settled": [], "mark": self.ledger.append("mark", {"value": "1000"})}
        ),
    )
    monkeypatch.setattr(Exchange, "resolve_forecasts", lambda self, cache: [])
    start = datetime.now(UTC) - timedelta(days=8)
    runner.create_run("ended", model="m", arm="evolving", days=7, start=start)
    assert runner.tick()["ended"]["final"] is False
    assert runner.tick()["ended"]["final"] is True
    assert len(marked) == 1
