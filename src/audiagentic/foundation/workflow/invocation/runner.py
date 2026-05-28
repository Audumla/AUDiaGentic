from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import WorkflowAnswer, WorkflowInvocationResult, WorkflowProgress
from .steps import WorkflowStep


@dataclass
class WorkflowInvocationRunner:
    steps: list[WorkflowStep]

    def plan(self, context: dict[str, Any]) -> WorkflowInvocationResult:
        outputs: dict[str, Any] = {}
        progress: list[WorkflowProgress] = []
        for step in self.steps:
            result = step.plan(context)
            outputs[step.id] = result.outputs
            progress.extend(result.progress)
            if result.status == "failed":
                return WorkflowInvocationResult(
                    status="failed",
                    outputs=outputs,
                    progress=progress,
                    failed_step=step.id,
                    reason=result.reason,
                )
        return WorkflowInvocationResult(status="planned", outputs=outputs, progress=progress)

    def run(
        self,
        context: dict[str, Any],
        answers: dict[str, WorkflowAnswer] | None = None,
    ) -> WorkflowInvocationResult:
        outputs: dict[str, Any] = {}
        progress: list[WorkflowProgress] = []
        for step in self.steps:
            result = step.run(context, answers)
            outputs[step.id] = result.outputs
            progress.extend(result.progress)
            if result.status == "waiting_for_input":
                return WorkflowInvocationResult(
                    status="waiting_for_input",
                    outputs=outputs,
                    progress=progress,
                    question=result.question,
                )
            if result.status == "skipped":
                return WorkflowInvocationResult(
                    status="skipped",
                    outputs=outputs,
                    progress=progress,
                    failed_step=step.id,
                    reason=result.reason,
                )
            if result.status == "failed":
                return WorkflowInvocationResult(
                    status="failed",
                    outputs=outputs,
                    progress=progress,
                    failed_step=step.id,
                    reason=result.reason,
                )
        return WorkflowInvocationResult(status="ok", outputs=outputs, progress=progress)
