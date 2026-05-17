from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass

from ..base import InvocationRecipe
from ..context import InvocationContext
from ..result import InvocationResult


@dataclass(frozen=True)
class ShellRecipe(InvocationRecipe):
    command: tuple[str, ...]

    def plan(self, context: InvocationContext) -> InvocationResult:
        return InvocationResult(status="planned", command=list(self.command))

    def run(self, context: InvocationContext) -> InvocationResult:
        if context.dry_run:
            return self.plan(context)
        manager = self.command[0]
        if shutil.which(manager) is None:
            return InvocationResult(
                status="failed",
                command=list(self.command),
                reason=f"{manager} is not available on PATH",
            )
        try:
            completed = subprocess.run(
                list(self.command),
                check=False,
                capture_output=True,
                text=True,
                timeout=context.timeout,
            )
        except subprocess.TimeoutExpired:
            return InvocationResult(
                status="failed",
                command=list(self.command),
                reason=f"timed out after {context.timeout}s",
            )
        except Exception as exc:  # noqa: BLE001
            return InvocationResult(
                status="failed",
                command=list(self.command),
                reason=str(exc),
            )
        return InvocationResult(
            status="ok" if completed.returncode == 0 else "failed",
            command=list(self.command),
            returncode=completed.returncode,
            stdout=completed.stdout.strip(),
            stderr=completed.stderr.strip(),
        )
