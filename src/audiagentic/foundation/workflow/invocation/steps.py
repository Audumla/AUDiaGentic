from __future__ import annotations

import os
import shutil
import subprocess
import threading
from dataclasses import dataclass
from typing import Any, Protocol

from .models import StepResult, WorkflowAnswer, WorkflowQuestion


class WorkflowStep(Protocol):
    id: str

    def plan(self, context: dict[str, Any]) -> StepResult: ...

    def run(
        self, context: dict[str, Any], answers: dict[str, WorkflowAnswer] | None = None
    ) -> StepResult: ...


@dataclass(frozen=True)
class ConfirmStep:
    id: str
    prompt: str
    default: str = "yes"
    metadata: dict[str, Any] | None = None

    def plan(self, context: dict[str, Any]) -> StepResult:
        return StepResult(status="planned")

    def run(
        self, context: dict[str, Any], answers: dict[str, WorkflowAnswer] | None = None
    ) -> StepResult:
        answer = (answers or {}).get(self.id)
        if answer is None:
            return StepResult(
                status="waiting_for_input",
                question=WorkflowQuestion(
                    id=self.id,
                    prompt=self.prompt.format(**context),
                    kind="confirm",
                    options=[
                        {"id": "yes", "label": "Yes"},
                        {"id": "no", "label": "No"},
                    ],
                    default=self.default,
                    metadata=dict(self.metadata or {}),
                ),
            )
        value = str(answer.value).lower()
        if value not in {"yes", "y", "true", "1"}:
            return StepResult(status="skipped", reason="confirmation declined")
        return StepResult(status="ok")


@dataclass(frozen=True)
class ShellStep:
    id: str
    command: tuple[str, ...]
    timeout: int = 300
    dry_run: bool = False
    cwd: str | None = None
    env: dict[str, str] | None = None
    progress_callback: Any | None = None

    def plan(self, context: dict[str, Any]) -> StepResult:
        return StepResult(status="planned", outputs={"command": list(self._render_command(context))})

    def run(
        self, context: dict[str, Any], answers: dict[str, WorkflowAnswer] | None = None
    ) -> StepResult:
        if self.dry_run:
            return self.plan(context)

        command = self._render_command(context)
        manager = command[0]
        if shutil.which(manager) is None:
            return StepResult(
                status="failed",
                outputs={"command": list(command)},
                reason=f"{manager} is not available on PATH",
            )

        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        if self.env:
            env.update(self.env)

        try:
            process = subprocess.Popen(
                list(command),
                cwd=self.cwd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=env,
            )
            output_lines: list[str] = []
            if self.progress_callback is not None:
                def _read_output() -> None:
                    assert process.stdout is not None
                    for line in process.stdout:
                        stripped = line.rstrip("\n\r")
                        output_lines.append(stripped)
                        self.progress_callback(stripped)

                reader = threading.Thread(target=_read_output, daemon=True)
                reader.start()
                process.wait(timeout=self.timeout)
                reader.join(timeout=1)
            else:
                stdout_data, _ = process.communicate(timeout=self.timeout)
                output_lines = stdout_data.splitlines()
            returncode = process.returncode
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
            return StepResult(
                status="failed",
                outputs={"command": list(command)},
                reason=f"timed out after {self.timeout}s",
            )
        except Exception as exc:
            return StepResult(status="failed", outputs={"command": list(command)}, reason=str(exc))

        return StepResult(
            status="ok" if returncode == 0 else "failed",
            outputs={
                "command": list(command),
                "returncode": returncode,
                "stdout": "\n".join(output_lines),
                "stderr": "",
            },
        )

    def _render_command(self, context: dict[str, Any]) -> tuple[str, ...]:
        return tuple(part.format(**context) for part in self.command)


@dataclass(frozen=True)
class CallableStep:
    id: str
    fn: Any
    dry_run: bool = False

    def plan(self, context: dict[str, Any]) -> StepResult:
        return StepResult(
            status="planned",
            outputs={"callable": getattr(self.fn, "__name__", type(self.fn).__name__)},
        )

    def run(
        self, context: dict[str, Any], answers: dict[str, WorkflowAnswer] | None = None
    ) -> StepResult:
        if self.dry_run:
            return self.plan(context)
        try:
            completed = self.fn(project_root=context.get("project_root"))
        except Exception as exc:
            return StepResult(status="failed", reason=str(exc))

        return StepResult(
            status="ok" if completed.returncode == 0 else "failed",
            outputs={
                "returncode": completed.returncode,
                "stdout": completed.stdout.strip() if completed.stdout else "",
                "stderr": completed.stderr.strip() if completed.stderr else "",
            },
            reason=None if completed.returncode == 0 else (completed.stderr or completed.stdout or "").strip() or None,
        )


@dataclass(frozen=True)
class SequenceStep:
    id: str
    steps: tuple[WorkflowStep, ...]
    fail_fast: bool = True

    def plan(self, context: dict[str, Any]) -> StepResult:
        outputs: dict[str, Any] = {}
        for step in self.steps:
            result = step.plan(context)
            outputs[step.id] = result.outputs
        return StepResult(status="planned", outputs=outputs)

    def run(
        self, context: dict[str, Any], answers: dict[str, WorkflowAnswer] | None = None
    ) -> StepResult:
        outputs: dict[str, Any] = {}
        for step in self.steps:
            result = step.run(context, answers)
            outputs[step.id] = result.outputs
            if self.fail_fast and result.status in {"failed", "skipped", "waiting_for_input"}:
                return StepResult(
                    status=result.status,
                    outputs=outputs,
                    question=result.question,
                    reason=result.reason,
                )
        return StepResult(status="ok", outputs=outputs)


@dataclass(frozen=True)
class ConditionalStep:
    id: str
    condition_key: str
    when_true: WorkflowStep
    when_false: WorkflowStep | None = None

    def plan(self, context: dict[str, Any]) -> StepResult:
        return StepResult(status="planned", reason="conditional branch resolved at runtime")

    def run(
        self, context: dict[str, Any], answers: dict[str, WorkflowAnswer] | None = None
    ) -> StepResult:
        if bool(context.get(self.condition_key)):
            return self.when_true.run(context, answers)
        if self.when_false is not None:
            return self.when_false.run(context, answers)
        return StepResult(status="skipped", reason="condition not met")
