"""Managed text-block provisioning step (self-reverting)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.foundation.workflow.invocation.models import StepResult

from ..artifact_registry import ArtifactRegistry
from ..managed_block import apply_managed_block, remove_managed_block
from .base import _substitute, register_step_type


class ManagedBlockStep:
    """Apply or remove a managed text block; self-reverting."""

    def __init__(
        self,
        id: str,
        path: str,
        block_id: str,
        content: str,
        *,
        registry: ArtifactRegistry | None = None,
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
        resolved = _substitute(self.content, {k: str(v) for k, v in context.items()})
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
            outputs={
                "path": self.path,
                "block_id": self.block_id,
                "existed": change.existed,
            },
        )

    def revert(self, context: dict[str, Any]) -> StepResult:
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
            outputs={
                "path": self.path,
                "block_id": self.block_id,
                "existed": change.existed,
            },
        )

    def dry_run(self, context: dict[str, Any]) -> StepResult:
        return StepResult(
            status="planned",
            outputs={
                "path": self.path,
                "block_id": self.block_id,
            },
        )


def _managed_block_from_dict(
    data: dict[str, Any],
    params: dict[str, str],
    registry: ArtifactRegistry | None,
    recipe_id: str | None,
) -> ManagedBlockStep:
    step_id = data.get("id", "managed-block-anonymous")
    raw_content = data.get("content", "")
    content = _substitute(raw_content, params, f"step.{step_id}.content")
    return ManagedBlockStep(
        id=step_id,
        path=data["path"],
        block_id=data["block_id"],
        content=content,
        registry=registry,
        recipe_id=recipe_id,
        comment_prefix=data.get("comment_prefix", "#"),
    )


register_step_type("managed-block", _managed_block_from_dict)
