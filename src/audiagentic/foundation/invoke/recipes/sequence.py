from __future__ import annotations

from dataclasses import dataclass

from ..base import InvocationRecipe
from ..context import InvocationContext
from ..result import InvocationResult


@dataclass(frozen=True)
class SequenceRecipe(InvocationRecipe):
    steps: tuple[InvocationRecipe, ...]
    fail_fast: bool = True

    def plan(self, context: InvocationContext) -> InvocationResult:
        return InvocationResult(
            status="planned",
            steps=[s.plan(context) for s in self.steps],
        )

    def run(self, context: InvocationContext) -> InvocationResult:
        if context.dry_run:
            return self.plan(context)
        step_results: list[InvocationResult] = []
        for step in self.steps:
            result = step.run(context)
            step_results.append(result)
            if self.fail_fast and result.status == "failed":
                return InvocationResult(
                    status="failed",
                    steps=step_results,
                    reason=result.reason or "step failed",
                )
        final = "ok" if all(r.status == "ok" for r in step_results) else "failed"
        return InvocationResult(status=final, steps=step_results)
