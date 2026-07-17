"""Frozen Hindsight-owned Codex and Pi desired state.

Parse once at the boundary; no Any payloads past this module.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from audiagentic.components.memory.hindsight.export import HindsightBackendConfig

_SCHEMA_DIR = Path(__file__).resolve().parents[3] / "config" / "components" / "memory"


def _load_schema(name: str) -> dict[str, Any]:
    """Load a v1 JSON schema from the memory config directory."""
    path = _SCHEMA_DIR / f"{name}.schema.json"
    if not path.exists():
        raise FileNotFoundError(f"schema not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Hook command — per-event entry (Codex only)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HookCommand:
    """Single per-event hook command entry."""

    event: str
    command: str
    timeout: int

    def to_mapping(self) -> dict[str, Any]:
        return {
            "event": self.event,
            "command": self.command,
            "timeout": self.timeout,
        }

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> HookCommand:
        return cls(
            event=str(value["event"]),
            command=str(value["command"]),
            timeout=int(value["timeout"]),
        )


# ---------------------------------------------------------------------------
# Codex Hindsight desired state
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CodexHindsightDesired:
    """Frozen, Hindsight-owned Codex desired configuration."""

    base_url: str
    bank_id: str
    api_key: str | None = None
    interpreter_path: Path | None = None
    script_dir: Path | None = None
    hook_commands: tuple[HookCommand, ...] = ()

    def __post_init__(self) -> None:
        if not self.base_url:
            raise ValueError("base_url must be non-empty")
        if not self.bank_id:
            raise ValueError("bank_id must be non-empty")
        events = [hc.event for hc in self.hook_commands]
        if len(events) != len(set(events)):
            raise ValueError("hook event names must be unique")

    def to_mapping(self) -> dict[str, Any]:
        return {
            "base_url": self.base_url,
            "bank_id": self.bank_id,
            "api_key": self.api_key,
            "interpreter_path": str(self.interpreter_path) if self.interpreter_path else None,
            "script_dir": str(self.script_dir) if self.script_dir else None,
            "hook_commands": [hc.to_mapping() for hc in self.hook_commands],
        }

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> CodexHindsightDesired:
        return cls(
            base_url=str(value["base_url"]),
            bank_id=str(value["bank_id"]),
            api_key=value.get("api_key"),
            interpreter_path=Path(value["interpreter_path"])
            if value.get("interpreter_path")
            else None,
            script_dir=Path(value["script_dir"]) if value.get("script_dir") else None,
            hook_commands=tuple(
                HookCommand.from_mapping(hc) for hc in value.get("hook_commands", [])
            ),
        )

    @classmethod
    def from_backend(cls, backend: HindsightBackendConfig) -> CodexHindsightDesired:
        return cls(
            base_url=backend.base_url,
            bank_id=backend.bank_id or "codex",
            api_key=backend.api_key,
        )


# ---------------------------------------------------------------------------
# Pi host block — per-provider config inside ~/.hindsight/config.json
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PiHostBlock:
    """Frozen representation of the pi host block in ~/.hindsight/config.json."""

    enabled: bool = True
    recall_mode: str = "hybrid"
    auto_recall_tags: tuple[str, ...] = ("{project}",)
    auto_recall_tags_match: str = "any_strict"
    observation_scopes: tuple[tuple[str, ...], ...] = (("{project}",),)

    def to_mapping(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "recall_mode": self.recall_mode,
            "auto_recall_tags": list(self.auto_recall_tags),
            "auto_recall_tags_match": self.auto_recall_tags_match,
            "observation_scopes": [list(s) for s in self.observation_scopes],
        }

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> PiHostBlock:
        return cls(
            enabled=bool(value.get("enabled", True)),
            recall_mode=str(value.get("recall_mode", "hybrid")),
            auto_recall_tags=tuple(str(t) for t in value.get("auto_recall_tags", ["{project}"])),
            auto_recall_tags_match=str(value.get("auto_recall_tags_match", "any_strict")),
            observation_scopes=tuple(
                tuple(str(s) for s in scope)
                for scope in value.get("observation_scopes", [("{project}",)])
            ),
        )


# ---------------------------------------------------------------------------
# Pi Hindsight desired state
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PiHindsightDesired:
    """Frozen, Hindsight-owned Pi desired configuration."""

    base_url: str
    bank_id: str
    bank_strategy: str = "manual"
    pi_host_block: PiHostBlock | None = None

    def __post_init__(self) -> None:
        if not self.base_url:
            raise ValueError("base_url must be non-empty")
        if not self.bank_id:
            raise ValueError("bank_id must be non-empty")

    def to_mapping(self) -> dict[str, Any]:
        return {
            "base_url": self.base_url,
            "bank_id": self.bank_id,
            "bank_strategy": self.bank_strategy,
            "pi_host_block": self.pi_host_block.to_mapping() if self.pi_host_block else None,
        }

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> PiHindsightDesired:
        return cls(
            base_url=str(value["base_url"]),
            bank_id=str(value["bank_id"]),
            bank_strategy=str(value.get("bank_strategy", "manual")),
            pi_host_block=PiHostBlock.from_mapping(value["pi_host_block"])
            if value.get("pi_host_block")
            else None,
        )

    @classmethod
    def from_backend(cls, backend: HindsightBackendConfig) -> PiHindsightDesired:
        return cls(
            base_url=backend.base_url,
            bank_id=backend.bank_id or "audiagentic",
        )


# ---------------------------------------------------------------------------
# Boundary parsers — validate against schema, return frozen dataclass
# ---------------------------------------------------------------------------


def parse_codex_hindsight_desired(data: dict[str, Any]) -> CodexHindsightDesired:
    """Validate a mapping against the codex-hindsight-desired/v1 schema and return a frozen instance.

    Raises ValueError with all validation error messages on failure.
    """
    schema = _load_schema("codex-hindsight-desired")
    validator = Draft202012Validator(schema)
    errors = list(validator.iter_errors(data))
    if errors:
        messages = sorted(e.message for e in errors)
        raise ValueError(f"codex-hindsight-desired validation failed: {'; '.join(messages)}")
    return CodexHindsightDesired.from_mapping(data)


def parse_pi_hindsight_desired(data: dict[str, Any]) -> PiHindsightDesired:
    """Validate a mapping against the pi-hindsight-desired/v1 schema and return a frozen instance.

    Raises ValueError with all validation error messages on failure.
    """
    schema = _load_schema("pi-hindsight-desired")
    validator = Draft202012Validator(schema)
    errors = list(validator.iter_errors(data))
    if errors:
        messages = sorted(e.message for e in errors)
        raise ValueError(f"pi-hindsight-desired validation failed: {'; '.join(messages)}")
    return PiHindsightDesired.from_mapping(data)


__all__ = [
    "CodexHindsightDesired",
    "HookCommand",
    "PiHindsightDesired",
    "PiHostBlock",
    "parse_codex_hindsight_desired",
    "parse_pi_hindsight_desired",
]
