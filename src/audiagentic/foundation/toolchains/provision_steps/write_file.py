"""File-write provisioning step (self-reverting)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.foundation.workflow.invocation.models import StepResult

from ..artifact_registry import ArtifactRegistry
from .base import _substitute, register_step_type


class WriteFileStep:
    """Write file content; self-reverting."""

    def __init__(
        self,
        id: str,
        path: str,
        content: str,
        *,
        create_parents: bool = True,
        registry: ArtifactRegistry | None = None,
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
        resolved = _substitute(self.content, {k: str(v) for k, v in context.items()})
        target = Path(self.path).expanduser()
        existed = target.exists()
        prior = None

        if existed:
            prior = target.read_text(encoding="utf-8")

        if self.create_parents:
            target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(resolved, encoding="utf-8")

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
            outputs={
                "path": self.path,
                "created": not existed,
            },
        )

    def revert(self, context: dict[str, Any]) -> StepResult:
        if not self._ran:
            return StepResult(status="skipped", reason="run never succeeded")

        target = Path(self.path).expanduser()
        if not self._prior_existed and target.exists():
            target.unlink()
        elif self._prior_content is not None:
            target.write_text(self._prior_content, encoding="utf-8")

        return StepResult(
            status="ok",
            outputs={"path": self.path},
        )

    def dry_run(self, context: dict[str, Any]) -> StepResult:
        return StepResult(
            status="planned",
            outputs={
                "path": self.path,
                "create_parents": self.create_parents,
            },
        )


def _write_file_from_dict(
    data: dict[str, Any],
    params: dict[str, str],
    registry: ArtifactRegistry | None,
    recipe_id: str | None,
) -> WriteFileStep:
    step_id = data.get("id", "write-file-anonymous")
    raw_content = data.get("content", "")
    content = _substitute(raw_content, params, f"step.{step_id}.content")
    return WriteFileStep(
        id=step_id,
        path=data["path"],
        content=content,
        create_parents=data.get("create_parents", True),
        registry=registry,
        recipe_id=recipe_id,
    )


register_step_type("write-file", _write_file_from_dict)
