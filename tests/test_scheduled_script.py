import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_scheduled_cycle.sh"


def test_scheduled_script_is_fixed_to_paper_only_mandate(tmp_path):
    trace = tmp_path / "trace"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    uv = fake_bin / "uv"
    uv.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$TRACE"\n')
    uv.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:/usr/bin:/bin",
        "TRACE": str(trace),
        "MANDATE": "examples/mandate.index-dca-live.example.json",
    }

    result = subprocess.run([str(SCRIPT)], cwd=ROOT, env=env, check=False)

    assert result.returncode == 0
    calls = trace.read_text().splitlines()
    assert calls == [
        "run --no-sync edgecraft health --real-data-symbol SPY --ledger state/edgecraft-paper.db",
        "run --no-sync edgecraft readiness --mandate examples/mandate.index-dca.json "
        "--ledger state/edgecraft-paper.db --require-ready",
        "run --no-sync edgecraft cycle --mandate examples/mandate.index-dca.json "
        "--ledger state/edgecraft-paper.db --paper-only",
    ]


def test_scheduled_script_stops_after_failed_readiness(tmp_path):
    trace = tmp_path / "trace"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    uv = fake_bin / "uv"
    uv.write_text(
        '#!/bin/sh\nprintf "%s\\n" "$*" >> "$TRACE"\ncase "$*" in *readiness*) exit 1;; esac\n'
    )
    uv.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:/usr/bin:/bin",
        "TRACE": str(trace),
    }

    result = subprocess.run([str(SCRIPT)], cwd=ROOT, env=env, check=False)

    assert result.returncode == 1
    calls = trace.read_text().splitlines()
    assert len(calls) == 2
    assert " health " in f" {calls[0]} "
    assert " readiness " in f" {calls[1]} "
