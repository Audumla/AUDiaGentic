from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ..base import InvocationRecipe
from ..context import InvocationContext
from ..result import InvocationResult


@dataclass(frozen=True)
class ConditionalRecipe(InvocationRecipe):
    condition: Callable[[InvocationContext], bool]
    when_true: InvocationRecipe
    when_false: InvocationRecipe | None = None

    def plan(self, context: InvocationContext) -> InvocationResult:
        return InvocationResult(
            status="planned",
            reason="conditional: branch resolved at runtime",
        )

    def run(self, context: InvocationContext) -> InvocationResult:
        if context.dry_run:
            return self.plan(context)
        if self.condition(context):
            return self.when_true.run(context)
        if self.when_false is not None:
            return self.when_false.run(context)
        return InvocationResult(status="skipped", reason="condition not met")
