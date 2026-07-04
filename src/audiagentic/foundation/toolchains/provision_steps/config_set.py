"""Config-key provisioning step (self-reverting)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.foundation.workflow.invocation.models import StepResult

from ..artifact_registry import ArtifactRegistry
from ..config_patcher import ConfigPatcher, OwnedChange
from .base import _pstep_error, _substitute, register_step_type


class ConfigSetStep:
    """Set a key in a structured config file; self-reverting."""

    def __init__(
        self,
        id: str,
        path: str,
        key_path: tuple[str, ...],
        value: Any,
        *,
        registry: ArtifactRegistry | None = None,
        recipe_id: str | None = None,
    ) -> None:
        self.id = id
        self.path = path
        self.key_path = key_path
        self.value = value
        self.registry = registry
        self.recipe_id = recipe_id
        self._change: OwnedChange | None = None

    def run(self, context: dict[str, Any]) -> StepResult:
        resolved_value = _substitute(self.value, {k: str(v) for k, v in context.items()})
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

    def revert(self, context: dict[str, Any]) -> StepResult:
        if self._change is None:
            return StepResult(status="skipped", reason="run never succeeded")
        ConfigPatcher(self.path).revert(self._change)
        return StepResult(
            status="ok",
            outputs={
                "path": self.path,
                "key": ".".join(self.key_path),
            },
        )

    def dry_run(self, context: dict[str, Any]) -> StepResult:
        return StepResult(
            status="planned",
            outputs={
                "path": self.path,
                "key": ".".join(self.key_path),
            },
        )


def _config_set_from_dict(
    data: dict[str, Any],
    params: dict[str, str],
    registry: ArtifactRegistry | None,
    recipe_id: str | None,
) -> ConfigSetStep:
    step_id = data.get("id", "config-set-anonymous")
    kp = data.get("key_path")
    if kp is None:
        raise _pstep_error(2, f"config-set step {step_id!r} missing 'key_path'")
    if isinstance(kp, str):
        key_path = tuple(kp.split("."))
    else:
        key_path = tuple(kp)
    raw_value = data.get("value")
    value = _substitute(raw_value, params, f"step.{step_id}.value")
    return ConfigSetStep(
        id=step_id,
        path=data["path"],
        key_path=key_path,
        value=value,
        registry=registry,
        recipe_id=recipe_id,
    )


register_step_type("config-set", _config_set_from_dict)
