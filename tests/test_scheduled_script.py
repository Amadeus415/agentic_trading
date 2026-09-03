import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from edgecraft.schedule import scheduled_cycle_key

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_scheduled_cycle.sh"


def test_scheduled_script_is_fixed_to_paper_fund(tmp_path):
    trace = tmp_path / "trace"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    uv = fake_bin / "uv"
    uv.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$TRACE"\n')
    uv.chmod(0o755)
    input_path = tmp_path / "input.json"
    input_path.write_text("{}")
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:/usr/bin:/bin",
        "TRACE": str(trace),
        "FUND_INPUT": str(input_path),
    }

    result = subprocess.run([str(SCRIPT)], cwd=ROOT, env=env, check=False)

    assert result.returncode == 0
    calls = trace.read_text().splitlines()
    assert calls == [
        "run --no-sync edgecraft fund-init --config examples/fund.mandate.aggressive.json "
        "--ledger state/edgecraft-aggressive.db",
        "run --no-sync edgecraft fund-verify --config examples/fund.mandate.aggressive.json "
        "--ledger state/edgecraft-aggressive.db",
        "run --no-sync edgecraft fund-run --config examples/fund.mandate.aggressive.json "
        f"--input {input_path} --ledger state/edgecraft-aggressive.db --require-as-of-today "
        "--max-decision-age-seconds 1800 --require-cycle-key "
        f"{scheduled_cycle_key(datetime.now(UTC))} --require-brain-journal "
        "--code-owned-quotes --size-beliefs",
        "run --no-sync edgecraft fund-verify --config examples/fund.mandate.aggressive.json "
        "--ledger state/edgecraft-aggressive.db",
        "run --no-sync edgecraft fund-visualize --config examples/fund.mandate.aggressive.json "
        "--ledger state/edgecraft-aggressive.db --output assets/fund-progress.svg",
        "run --no-sync edgecraft fund-report --config examples/fund.mandate.aggressive.json "
        "--ledger state/edgecraft-aggressive.db --output state/fund-report.json",
    ]


def test_scheduled_script_stops_after_failed_preflight_verification(tmp_path):
    trace = tmp_path / "trace"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    uv = fake_bin / "uv"
    uv.write_text(
        '#!/bin/sh\nprintf "%s\\n" "$*" >> "$TRACE"\ncase "$*" in *fund-verify*) exit 1;; esac\n'
    )
    uv.chmod(0o755)
    input_path = tmp_path / "input.json"
    input_path.write_text("{}")
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:/usr/bin:/bin",
        "TRACE": str(trace),
        "FUND_INPUT": str(input_path),
    }

    result = subprocess.run([str(SCRIPT)], cwd=ROOT, env=env, check=False)

    assert result.returncode == 1
    calls = trace.read_text().splitlines()
    assert len(calls) == 2
    assert " fund-init " in f" {calls[0]} "
    assert " fund-verify " in f" {calls[1]} "


def test_scheduled_script_refuses_missing_input(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    uv = fake_bin / "uv"
    uv.write_text("#!/bin/sh\nexit 99\n")
    uv.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:/usr/bin:/bin",
        "FUND_INPUT": str(tmp_path / "missing.json"),
    }

    result = subprocess.run([str(SCRIPT)], cwd=ROOT, env=env, check=False)

    assert result.returncode == 2
