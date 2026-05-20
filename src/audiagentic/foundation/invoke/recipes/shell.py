from __future__ import annotations

import os
import shutil
import subprocess
import threading
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
        if context.on_progress is not None:
            context.on_progress(f"Running: {' '.join(self.command)}")

        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONDONTWRITEBYTECODE"] = "1"

        try:
            process = subprocess.Popen(
                list(self.command),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=env,
            )
            output_lines: list[str] = []
            if context.on_progress is not None:
                def _read_output() -> None:
                    assert process.stdout is not None
                    for line in process.stdout:
                        stripped = line.rstrip("\n\r")
                        output_lines.append(stripped)
                        context.on_progress(stripped)

                reader = threading.Thread(target=_read_output, daemon=True)
                reader.start()
                process.wait(timeout=context.timeout)
                reader.join(timeout=1)
            else:
                stdout_data, _ = process.communicate(timeout=context.timeout)
                output_lines = stdout_data.splitlines()

            returncode = process.returncode
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
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
        if context.on_progress is not None:
            context.on_progress(f"Completed (rc={returncode})")
        return InvocationResult(
            status="ok" if returncode == 0 else "failed",
            command=list(self.command),
            returncode=returncode,
            stdout="\n".join(output_lines),
            stderr="",
        )
