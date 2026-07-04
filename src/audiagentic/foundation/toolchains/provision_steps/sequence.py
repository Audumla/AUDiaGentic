"""Compensating sequence — run steps forward, revert committed on failure (TO11)."""
from __future__ import annotations

import logging
from collections.abc import Sequence as _Sequence
from typing import Any

from audiagentic.foundation.workflow.invocation.models import StepResult

from .base import ProvisionStep

logger = logging.getLogger(__name__)

_comp_ok_statuses = {"ok"}
_comp_success_statuses = {"ok", "skipped"}
_comp_dry_run_success = {"planned", "ok", "skipped"}


class CompensatingSequence:
    """Execute steps forward; on failure revert committed steps in reverse.

    Rollback semantics:
    - ``ok`` run status → committed (will be reverted on failure)
    - ``skipped`` run status → successful no-op, not committed, not reverted
    - All other statuses → failure, triggers rollback of committed steps

    Revert is best-effort: failures are logged and captured in result details,
    but never mask the original run failure.
    """

    def __init__(
        self,
        steps: _Sequence[ProvisionStep],
        *,
        id: str = "compensating-sequence",
    ) -> None:
        self.id = id
        self._steps = list(steps)

    def run(self, context: dict[str, Any]) -> StepResult:
        committed: list[ProvisionStep] = []
        per_step: list[dict[str, Any]] = []

        for step in self._steps:
            try:
                result = step.run(context)
            except Exception as exc:
                result = StepResult(
                    status="failed",
                    reason=str(exc),
                )

            per_step.append({
                "id": step.id,
                "status": result.status,
                "outputs": dict(result.outputs),
            })

            if result.status in _comp_ok_statuses:
                committed.append(step)
            elif result.status not in _comp_success_statuses:
                rollback = self._rollback(committed, context)
                per_step.extend(rollback)
                return StepResult(
                    status="failed",
                    outputs={"steps": per_step},
                    reason=result.reason,
                )

        return StepResult(status="ok", outputs={"steps": per_step})

    def revert(self, context: dict[str, Any]) -> StepResult:
        results = self._rollback(list(self._steps), context)
        any_failure = any(
            r.get("status") == "failed" for r in results
        )
        return StepResult(
            status="failed" if any_failure else "ok",
            outputs={"rollback_steps": results},
        )

    def dry_run(self, context: dict[str, Any]) -> StepResult:
        per_step: list[dict[str, Any]] = []
        for step in self._steps:
            result = step.dry_run(context)
            per_step.append({
                "id": step.id,
                "status": result.status,
                "outputs": dict(result.outputs),
            })
            if result.status not in _comp_dry_run_success:
                return StepResult(
                    status="failed",
                    outputs={"steps": per_step},
                    reason=result.reason,
                )
        return StepResult(status="ok", outputs={"steps": per_step})

    def _rollback(
        self, committed: list[ProvisionStep], context: dict[str, Any]
    ) -> list[dict[str, Any]]:
        rollback_results: list[dict[str, Any]] = []
        for step in reversed(committed):
            try:
                result = step.revert(context)
                rollback_results.append({
                    "id": step.id,
                    "status": result.status,
                    "phase": "rollback",
                    "outputs": dict(result.outputs),
                })
            except Exception as exc:
                logger.warning(
                    "Revert of step %s failed: %s", step.id, exc, exc_info=True
                )
                rollback_results.append({
                    "id": step.id,
                    "status": "failed",
                    "phase": "rollback",
                    "reason": str(exc),
                })
        return rollback_results
