"""Structured mutation provisioning steps (self-reverting).

ConfigSetStep, WriteFileStep, and ManagedBlockStep reuse existing toolchain
primitives (ConfigPatcher, ArtifactRegistry, atomic_write_text, managed_block)
and do not duplicate ownership or IO logic.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.foundation.io import atomic_write_text

from .results import StepResult


class ConfigSetStep:
    """Set a key in a structured config file; self-reverting."""

    def __init__(
        self,
        id: str,
        path: str,
        key_path: tuple[str, ...],
        value: Any,
        *,
        registry: Any | None = None,
        recipe_id: str | None = None,
    ) -> None:
        self.id = id
        self.path = path
        self.key_path = key_path
        self.value = value
        self.registry = registry
        self.recipe_id = recipe_id
        self._change: Any | None = None

    def run(self, context: dict[str, Any]) -> StepResult:
        from audiagentic.foundation.toolchains.config_patcher import ConfigPatcher

        resolved_value = _substitute_value(self.value, context)
        resolved_path = Path(self.path).expanduser()
        change = ConfigPatcher(str(resolved_path)).set_key(self.key_path, resolved_value)
        self._change = change

        if self.registry is not None and self.recipe_id is not None:
            self.registry.register(
                self.recipe_id,
                changes=[change],
            )

        return StepResult(
            status="ok",
            outputs={
                "path": self.path,
                "key": ".".join(self.key_path),
                "existed": change.existed,
            },
        )

    def compensate(self, context: dict[str, Any]) -> StepResult:
        from audiagentic.foundation.toolchains.config_patcher import ConfigPatcher

        if self._change is None:
            return StepResult(status="skipped", reason="run never succeeded")
        ConfigPatcher(self.path).revert(self._change)
        return StepResult(
            status="ok",
            outputs={"path": self.path, "key": ".".join(self.key_path)},
        )

    def plan(self, context: dict[str, Any]) -> StepResult:
        return StepResult(
            status="planned",
            outputs={"path": self.path, "key": ".".join(self.key_path)},
        )


class WriteFileStep:
    """Write file content; self-reverting."""

    def __init__(
        self,
        id: str,
        path: str,
        content: str,
        *,
        create_parents: bool = True,
        registry: Any | None = None,
        recipe_id: str | None = None,
    ) -> None:
        self.id = id
        self.path = path
        self.content = content
        self.create_parents = create_parents
        self.registry = registry
        self.recipe_id = recipe_id
        self._prior_existed: bool = False
        self._prior_content: str | None = None
        self._ran = False

    def run(self, context: dict[str, Any]) -> StepResult:
        resolved = _substitute_value(self.content, context)
        target = Path(self.path).expanduser()
        existed = target.exists()
        prior = None

        if existed:
            prior = target.read_text(encoding="utf-8")

        if not self.create_parents and not target.parent.exists():
            return StepResult(
                status="failed",
                reason=f"parent directory does not exist: {target.parent}",
            )
        atomic_write_text(target, resolved)

        self._prior_existed = existed
        self._prior_content = prior
        self._ran = True

        if self.registry is not None and self.recipe_id is not None:
            self.registry.register(
                self.recipe_id,
                files=[self.path],
            )

        return StepResult(
            status="ok",
            outputs={"path": self.path, "created": not existed},
        )

    def compensate(self, context: dict[str, Any]) -> StepResult:
        if not self._ran:
            return StepResult(status="skipped", reason="run never succeeded")

        target = Path(self.path).expanduser()
        if not self._prior_existed and target.exists():
            target.unlink()
        elif self._prior_content is not None:
            atomic_write_text(target, self._prior_content)

        return StepResult(status="ok", outputs={"path": self.path})

    def plan(self, context: dict[str, Any]) -> StepResult:
        return StepResult(
            status="planned",
            outputs={"path": self.path, "create_parents": self.create_parents},
        )


class ManagedBlockStep:
    """Apply or remove a managed text block; self-reverting."""

    def __init__(
        self,
        id: str,
        path: str,
        block_id: str,
        content: str,
        *,
        registry: Any | None = None,
        recipe_id: str | None = None,
        comment_prefix: str = "#",
    ) -> None:
        self.id = id
        self.path = path
        self.block_id = block_id
        self.content = content
        self.registry = registry
        self.recipe_id = recipe_id
        self.comment_prefix = comment_prefix
        self._ran = False

    def run(self, context: dict[str, Any]) -> StepResult:
        from audiagentic.foundation.toolchains.managed_block import apply_managed_block

        resolved = _substitute_value(self.content, context)
        resolved_path = Path(self.path).expanduser()
        change = apply_managed_block(
            str(resolved_path),
            self.block_id,
            resolved,
            comment_prefix=self.comment_prefix,
        )
        self._ran = True

        if self.registry is not None and self.recipe_id is not None:
            self.registry.register(
                self.recipe_id,
                blocks=[change],
            )

        return StepResult(
            status="ok",
            outputs={"path": self.path, "block_id": self.block_id, "existed": change.existed},
        )

    def compensate(self, context: dict[str, Any]) -> StepResult:
        from audiagentic.foundation.toolchains.managed_block import remove_managed_block

        if not self._ran:
            return StepResult(status="skipped", reason="run never succeeded")
        resolved_path = Path(self.path).expanduser()
        change = remove_managed_block(
            str(resolved_path),
            self.block_id,
            comment_prefix=self.comment_prefix,
        )
        return StepResult(
            status="ok",
            outputs={"path": self.path, "block_id": self.block_id, "existed": change.existed},
        )

    def plan(self, context: dict[str, Any]) -> StepResult:
        return StepResult(
            status="planned",
            outputs={"path": self.path, "block_id": self.block_id},
        )


def _substitute_value(value: Any, context: dict[str, Any]) -> Any:
    """Recursively substitute {KEY} placeholders in strings using context values."""
    if isinstance(value, str):
        try:
            return value.format(**{k: str(v) for k, v in context.items()})
        except (KeyError, IndexError):
            return value
    if isinstance(value, list):
        return [_substitute_value(item, context) for item in value]
    if isinstance(value, dict):
        return {k: _substitute_value(v, context) for k, v in value.items()}
    return value
