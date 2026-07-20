from __future__ import annotations

import os
import plistlib
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from edgecraft.autonomy_models import Mandate


class SchedulerError(RuntimeError):
    pass


def launchd_label(mandate_id: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9.-]+", "-", mandate_id).strip("-").lower()
    if not safe:
        raise ValueError("mandate_id cannot produce an empty launchd label")
    return f"com.edgecraft.autonomy.{safe}"


def build_launchd_payload(
    repository: str | Path,
    mandate_path: str | Path,
    ledger_path: str | Path,
    *,
    mandate_id: str,
    interval_seconds: int = 1_800,
) -> dict[str, Any]:
    if interval_seconds < 300 or interval_seconds > 86_400:
        raise ValueError("interval_seconds must be between 300 and 86400")
    repository = Path(repository).resolve()
    mandate_path = _inside_or_absolute(repository, mandate_path)
    ledger_path = _inside_or_absolute(repository, ledger_path)
    uv = shutil.which("uv")
    codex = shutil.which("codex")
    if uv is None:
        raise SchedulerError("uv executable not found")
    if codex is None:
        raise SchedulerError("codex executable not found")

    log_directory = repository / "state" / "scheduler"
    log_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    log_directory.chmod(0o700)
    label = launchd_label(mandate_id)
    path_parts = [
        str(Path(uv).parent),
        str(Path(codex).parent),
        "/opt/homebrew/bin",
        "/usr/local/bin",
        "/usr/bin",
        "/bin",
    ]
    environment = {
        "PATH": ":".join(dict.fromkeys(path_parts)),
        "PYTHONUNBUFFERED": "1",
        "EDGECRAFT_LEDGER": str(ledger_path),
        "EDGECRAFT_LOG_LEVEL": os.getenv("EDGECRAFT_LOG_LEVEL", "INFO"),
    }
    if os.getenv("CODEX_HOME"):
        environment["CODEX_HOME"] = os.environ["CODEX_HOME"]
    return {
        "Label": label,
        "ProgramArguments": [
            uv,
            "run",
            "--project",
            str(repository),
            "edgecraft",
            "cycle",
            "--mandate",
            str(mandate_path),
            "--ledger",
            str(ledger_path),
        ],
        "WorkingDirectory": str(repository),
        "EnvironmentVariables": environment,
        "RunAtLoad": True,
        "StartInterval": interval_seconds,
        "Umask": 0o077,
        "ProcessType": "Background",
        "ThrottleInterval": 60,
        "StandardOutPath": str(log_directory / f"{mandate_id}.stdout.log"),
        "StandardErrorPath": str(log_directory / f"{mandate_id}.stderr.log"),
    }


def install_launchd_schedule(
    repository: str | Path,
    mandate_path: str | Path,
    ledger_path: str | Path,
    mandate: Mandate,
    *,
    interval_seconds: int = 1_800,
) -> dict[str, Any]:
    payload = build_launchd_payload(
        repository,
        mandate_path,
        ledger_path,
        mandate_id=mandate.mandate_id,
        interval_seconds=interval_seconds,
    )
    target = _launch_agents_directory() / f"{payload['Label']}.plist"
    target.parent.mkdir(parents=True, exist_ok=True)
    domain = f"gui/{os.getuid()}"
    subprocess.run(
        ["launchctl", "bootout", domain, str(target)],
        check=False,
        capture_output=True,
        text=True,
    )
    target.write_bytes(plistlib.dumps(payload, fmt=plistlib.FMT_XML, sort_keys=True))
    target.chmod(0o600)
    result = subprocess.run(
        ["launchctl", "bootstrap", domain, str(target)],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise SchedulerError(
            f"launchctl bootstrap failed ({result.returncode}): "
            f"{(result.stderr or result.stdout).strip()[-500:]}"
        )
    return {
        "ok": True,
        "label": payload["Label"],
        "plist": str(target),
        "interval_seconds": interval_seconds,
        "mandate_id": mandate.mandate_id,
        "mode": mandate.mode,
    }


def launchd_schedule_status(mandate_id: str) -> dict[str, Any]:
    label = launchd_label(mandate_id)
    service = f"gui/{os.getuid()}/{label}"
    result = subprocess.run(
        ["launchctl", "print", service],
        check=False,
        capture_output=True,
        text=True,
    )
    target = _launch_agents_directory() / f"{label}.plist"
    return {
        "ok": result.returncode == 0,
        "label": label,
        "loaded": result.returncode == 0,
        "plist_exists": target.exists(),
        "plist": str(target),
        "detail": (
            "loaded" if result.returncode == 0 else (result.stderr or result.stdout).strip()[-500:]
        ),
    }


def remove_launchd_schedule(mandate_id: str) -> dict[str, Any]:
    label = launchd_label(mandate_id)
    target = _launch_agents_directory() / f"{label}.plist"
    domain = f"gui/{os.getuid()}"
    result = subprocess.run(
        ["launchctl", "bootout", domain, str(target)],
        check=False,
        capture_output=True,
        text=True,
    )
    existed = target.exists()
    target.unlink(missing_ok=True)
    return {
        "ok": result.returncode == 0 or existed,
        "label": label,
        "removed": existed,
        "plist": str(target),
    }


def _inside_or_absolute(repository: Path, path: str | Path) -> Path:
    candidate = Path(path)
    return candidate.resolve() if candidate.is_absolute() else (repository / candidate).resolve()


def _launch_agents_directory() -> Path:
    return Path.home() / "Library" / "LaunchAgents"
