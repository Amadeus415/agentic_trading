from pathlib import Path

import pytest

from edgecraft.scheduler import build_launchd_payload, launchd_label


def test_launchd_payload_uses_one_safe_cli_path(tmp_path, monkeypatch):
    uv = tmp_path / "uv"
    codex = tmp_path / "codex"
    uv.touch()
    codex.touch()
    monkeypatch.setattr(
        "edgecraft.scheduler.shutil.which",
        lambda name: str(uv if name == "uv" else codex),
    )
    monkeypatch.setenv("BROWSERBASE_API_KEY", "must-not-enter-plist")
    monkeypatch.setenv("BROWSERBASE_API_KEY_FILE", "/private/context/browserbase-key")
    repository = tmp_path / "repo"
    repository.mkdir()
    payload = build_launchd_payload(
        repository,
        "examples/mandate.json",
        "state/edgecraft.db",
        mandate_id="index_dca",
        interval_seconds=1_800,
    )

    assert payload["Label"] == "com.edgecraft.autonomy.index-dca"
    args = payload["ProgramArguments"]
    assert args[:5] == [str(uv), "run", "--project", str(repository), "edgecraft"]
    assert args[5:7] == ["cycle", "--mandate"]
    assert "--force" not in args
    assert payload["RunAtLoad"] is True
    assert payload["StartInterval"] == 1_800
    assert payload["Umask"] == 0o077
    assert payload["EnvironmentVariables"]["BROWSERBASE_API_KEY_FILE"] == (
        "/private/context/browserbase-key"
    )
    assert "BROWSERBASE_API_KEY" not in payload["EnvironmentVariables"]
    assert Path(payload["StandardOutPath"]).parent == repository / "state" / "scheduler"
    assert (repository / "state" / "scheduler").stat().st_mode & 0o777 == 0o700


def test_launchd_label_and_interval_validation(tmp_path, monkeypatch):
    assert launchd_label("My Mandate_1") == "com.edgecraft.autonomy.my-mandate-1"
    with pytest.raises(ValueError, match="empty"):
        launchd_label("___")

    monkeypatch.setattr("edgecraft.scheduler.shutil.which", lambda name: f"/tmp/{name}")
    with pytest.raises(ValueError, match="between 300"):
        build_launchd_payload(
            tmp_path,
            "mandate.json",
            "state.db",
            mandate_id="test",
            interval_seconds=60,
        )
