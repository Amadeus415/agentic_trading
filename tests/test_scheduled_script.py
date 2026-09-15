import os
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from edgecraft.schedule import scheduled_cycle_key

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_scheduled_cycle.sh"


def isolated_script(tmp_path):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    script = scripts / SCRIPT.name
    shutil.copy2(SCRIPT, script)
    return script


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

    result = subprocess.run([str(isolated_script(tmp_path))], env=env, check=False)

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

    result = subprocess.run([str(isolated_script(tmp_path))], env=env, check=False)

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

    result = subprocess.run([str(isolated_script(tmp_path))], env=env, check=False)

    assert result.returncode == 2


def test_preparation_uses_installed_environment_without_network(tmp_path):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    script = scripts / "prepare_local_runtime.sh"
    shutil.copy2(ROOT / "scripts" / script.name, script)
    broken_bin = tmp_path / "broken-bin"
    working_bin = tmp_path / "working-bin"
    broken_bin.mkdir()
    working_bin.mkdir()
    broken_git = broken_bin / "git"
    broken_git.write_text('#!/bin/sh\necho "Xcode license required" >&2\nexit 69\n')
    broken_git.chmod(0o755)
    working_git = working_bin / "git"
    working_git.write_text(
        "#!/bin/sh\n"
        'case "$1 $2" in\n'
        '  "--version ") echo "git version test";;\n'
        '  "branch --show-current") echo "main";;\n'
        "esac\n"
    )
    working_git.chmod(0o755)
    binary = tmp_path / ".venv" / "bin" / "edgecraft"
    binary.parent.mkdir(parents=True)
    trace = tmp_path / "trace"
    binary.write_text('#!/bin/sh\nprintf "%s\\n" "$1" >> "$TRACE"\n')
    binary.chmod(0o755)
    result = subprocess.run(
        [str(script)],
        env={
            **os.environ,
            "TRACE": str(trace),
            "PATH": f"{broken_bin}:{working_bin}:/usr/bin:/bin",
        },
        check=False,
    )
    assert result.returncode == 0
    assert trace.read_text().splitlines() == ["fund-init", "fund-verify", "fund-report"]

    # A missing installation must fail instead of silently downloading packages.
    binary.unlink()
    result = subprocess.run(
        [str(script)],
        env={
            **os.environ,
            "TRACE": str(trace),
            "PATH": f"{broken_bin}:{working_bin}:/usr/bin:/bin",
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
