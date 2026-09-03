"""Versioned, file-backed trading playbooks."""

from __future__ import annotations

import hashlib
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class PlaybookStatus(StrEnum):
    PROPOSED = "proposed"
    VALIDATED = "validated"
    INCUBATING = "incubating"
    ACTIVE = "active"
    SHADOW = "shadow"
    FROZEN = "frozen"
    RETIRED = "retired"


class PlaybookSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{1,63}$")
    version: int = Field(ge=1)
    thesis: str = Field(min_length=1)
    universe: tuple[str, ...] = Field(min_length=1)
    trigger: str = Field(min_length=1)
    entry_rule: str = Field(min_length=1)
    exit_rule: str = Field(min_length=1)
    sizing_hints: str = Field(min_length=1)
    required_evidence_types: tuple[str, ...] = Field(min_length=1)
    status: PlaybookStatus
    prompt_path: str = "prompt.md"


class LoadedPlaybook(BaseModel):
    spec: PlaybookSpec
    prompt: str
    prompt_hash: str
    directory: str


def load_playbooks(root: Path = Path("playbooks")) -> tuple[LoadedPlaybook, ...]:
    loaded: list[LoadedPlaybook] = []
    if not root.exists():
        return ()
    for spec_path in sorted(root.glob("*/playbook.json")):
        spec = PlaybookSpec.model_validate_json(spec_path.read_text(encoding="utf-8"))
        prompt_path = spec_path.parent / spec.prompt_path
        prompt = prompt_path.read_text(encoding="utf-8").strip()
        digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        loaded.append(
            LoadedPlaybook(
                spec=spec,
                prompt=prompt,
                prompt_hash=digest,
                directory=str(spec_path.parent),
            )
        )
    ids = [item.spec.id for item in loaded]
    if len(ids) != len(set(ids)):
        raise ValueError("playbook IDs must be unique")
    return tuple(loaded)
