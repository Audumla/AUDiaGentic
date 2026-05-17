from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass

from ..base import InvocationRecipe
from ..context import InvocationContext
from ..result import InvocationResult


@dataclass(frozen=True)
class CallableRecipe(InvocationRecipe):
    """Wraps an arbitrary callable for provisioners with custom logic.

    fn signature: (project_root: Path | None) -> subprocess.CompletedProcess
    """
    fn: Callable[..., subprocess.CompletedProcess]
    label: str = ""

    def plan(self, context: InvocationContext) -> InvocationResult:
        return InvocationResult(
            status="planned",
            reason=f"callable: {self.label or 'custom provisioner'}",
        )

    def run(self, context: InvocationContext) -> InvocationResult:
        if context.dry_run:
            return self.plan(context)
        completed = self.fn(context.project_root)
        return InvocationResult(
            status="ok" if completed.returncode == 0 else "failed",
            returncode=completed.returncode,
            stdout=completed.stdout.strip() if completed.stdout else "",
            stderr=completed.stderr.strip() if completed.stderr else "",
        )
