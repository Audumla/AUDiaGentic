"""Ordered execution and reverse compensation for neutral steps."""
from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from .results import SequenceResult, StepResult

logger = logging.getLogger(__name__)

_COMMITTED = {"ok"}
_NON_FAILURE = {"ok", "skipped", "planned"}


class SequenceStep:
    """Run steps in order and compensate completed steps in reverse on failure."""

    def __init__(
        self,
        steps: Sequence[Any],
        *,
        id: str = "sequence",
        fail_fast: bool = True,
        compensate_on_failure: bool = False,
    ) -> None:
        self.id = id
        self.steps = tuple(steps)
        self.fail_fast = fail_fast
        self.compensate_on_failure = compensate_on_failure

    def plan(self, context: dict[str, Any]) -> SequenceResult:
        records: list[dict[str, Any]] = []
        outputs: dict[str, Any] = {}
        commands: list[list[str]] = []
        for step in self.steps:
            result = step.plan(context)
            records.append({"id": step.id, "status": result.status, "outputs": dict(result.outputs)})
            outputs[step.id] = result.outputs
            commands.extend(result.command_plan or self._commands_from(result))
            if self.fail_fast and result.status not in _NON_FAILURE:
                return SequenceResult(
                    status="failed",
                    outputs={"steps": records, **outputs},
                    reason=result.reason,
                    command_plan=commands,
                    failed_step=step.id,
                )
        return SequenceResult(status="planned", outputs={"steps": records, **outputs}, command_plan=commands)

    def run(self, context: dict[str, Any]) -> SequenceResult:
        committed: list[Any] = []
        records: list[dict[str, Any]] = []
        outputs: dict[str, Any] = {}
        statuses: dict[str, str] = {}
        for step in self.steps:
            try:
                child_context = {**context, "step_results": dict(outputs), "step_status": dict(statuses)}
                result = step.run(child_context)
            except Exception as exc:  # noqa: BLE001 - sequence owns compensation
                result = StepResult(status="failed", reason=str(exc))
            records.append({"id": step.id, "status": result.status, "outputs": dict(result.outputs)})
            outputs[step.id] = result.outputs
            statuses[step.id] = result.status
            if result.status in _COMMITTED:
                committed.append(step)
                continue
            if result.status in {"skipped", "waiting_for_input"}:
                if self.fail_fast:
                    return SequenceResult(
                        status=result.status,
                        outputs={"steps": records, **outputs},
                        reason=result.reason,
                        question=result.question,
                        failed_step=step.id,
                    )
                continue
            if result.status in _NON_FAILURE and not self.fail_fast:
                continue
            if result.status in _NON_FAILURE:
                return SequenceResult(
                    status=result.status,
                    outputs={"steps": records, **outputs},
                    reason=result.reason,
                    question=result.question,
                    failed_step=step.id,
                )
            if not self.fail_fast:
                continue
            compensation = self._compensate(committed, context) if self.compensate_on_failure else []
            return SequenceResult(
                status="failed",
                outputs={"steps": records, **outputs},
                reason=result.reason,
                compensation=compensation,
                failed_step=step.id,
            )
        failed = next((record for record in records if record["status"] not in _NON_FAILURE), None)
        if failed:
            compensation = self._compensate(committed, context) if self.compensate_on_failure else []
            return SequenceResult(
                status="failed",
                outputs={"steps": records, **outputs},
                reason=None,
                compensation=compensation,
                failed_step=failed["id"],
            )
        return SequenceResult(status="ok", outputs={"steps": records, **outputs})

    def compensate(self, context: dict[str, Any]) -> SequenceResult:
        compensation = self._compensate(list(self.steps), context)
        failed = next((entry for entry in compensation if entry["status"] == "failed"), None)
        return SequenceResult(
            status="failed" if failed else "ok",
            outputs={"rollback_steps": compensation},
            compensation=compensation,
            reason=failed.get("reason") if failed else None,
        )

    def _compensate(self, steps: list[Any], context: dict[str, Any]) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for step in reversed(steps):
            try:
                compensator = getattr(step, "compensate", None)
                if compensator is None:
                    results.append({"id": step.id, "status": "skipped", "phase": "compensation", "reason": "not compensable"})
                    continue
                result = compensator(context)
                results.append({"id": step.id, "status": result.status, "phase": "compensation", "outputs": dict(result.outputs)})
            except Exception as exc:  # noqa: BLE001 - preserve primary failure
                logger.warning("Compensation of step %s failed: %s", step.id, exc, exc_info=True)
                results.append({"id": step.id, "status": "failed", "phase": "compensation", "reason": str(exc)})
        return results

    @staticmethod
    def _commands_from(result: StepResult) -> list[list[str]]:
        command = result.outputs.get("command")
        if isinstance(command, list) and all(isinstance(part, str) for part in command):
            return [command]
        return []
