"""Canonical callable execution step."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from audiagentic.foundation.logging.redaction import truncate_output

from .results import StepResult


@dataclass(frozen=True)
class CallableStep:
    id: str
    fn: Any
    dry_run: bool = False

    def plan(self, context: dict[str, Any]) -> StepResult:
        return StepResult(status="planned", outputs={"callable": getattr(self.fn, "__name__", type(self.fn).__name__)})

    def run(self, context: dict[str, Any]) -> StepResult:
        if self.dry_run:
            return self.plan(context)
        try:
            completed = self.fn(project_root=context.get("project_root"))
        except Exception as exc:  # noqa: BLE001
            return StepResult(status="failed", reason=str(exc))
        stdout = truncate_output((completed.stdout or "").strip())
        stderr = truncate_output((completed.stderr or "").strip())
        return StepResult(
            status="ok" if completed.returncode == 0 else "failed",
            outputs={"returncode": completed.returncode, "stdout": stdout, "stderr": stderr},
            reason=None if completed.returncode == 0 else stderr or stdout or None,
        )
