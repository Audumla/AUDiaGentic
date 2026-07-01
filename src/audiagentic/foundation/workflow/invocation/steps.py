from __future__ import annotations

import os
import shutil
import subprocess
import threading
from dataclasses import dataclass
from typing import Any, Protocol

from audiagentic.runtime.system.platform import platform_key as _platform_key

from .models import StepResult, WorkflowAnswer, WorkflowQuestion


@dataclass(frozen=True)
class PlatformOverrides:
    """Strict per-platform command overrides for :class:`ShellStep` (RV01/RV02).

    Named fields instead of a free-form dict, so recipes cannot smuggle ad-hoc
    platform branching. :meth:`resolve` returns the command for the current
    platform, or ``None`` to fall back to the step's default ``command``.
    """

    win: tuple[str, ...] | None = None
    darwin: tuple[str, ...] | None = None
    linux: tuple[str, ...] | None = None

    def resolve(self, platform_key: str | None = None) -> tuple[str, ...] | None:
        key = platform_key or _platform_key()
        return {"win": self.win, "darwin": self.darwin, "linux": self.linux}.get(key)


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
    platform: PlatformOverrides | None = None

    def plan(self, context: dict[str, Any]) -> StepResult:
        return StepResult(status="planned", outputs={"command": list(self._render_command(context))})

    def run(
        self, context: dict[str, Any], answers: dict[str, WorkflowAnswer] | None = None
    ) -> StepResult:
        if self.dry_run:
            return self.plan(context)

        command = self._render_command(context)
        manager = command[0]
        resolved = shutil.which(manager)
        if resolved is None:
            return StepResult(
                status="failed",
                outputs={"command": list(command)},
                reason=f"{manager} is not available on PATH",
            )
        # Use the fully resolved path so Windows executes npm/.cmd/.bat shims:
        # bare Popen(["claude", ...]) fails with WinError 2 because it does not
        # apply PATHEXT, but shutil.which() does. No-op on POSIX.
        command = (resolved, *command[1:])

        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        if self.env:
            env.update(self.env)

        cwd = os.path.expanduser(self.cwd) if self.cwd else None

        process: subprocess.Popen[str] | None = None
        try:
            process = subprocess.Popen(
                list(command),
                cwd=cwd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                # Force UTF-8 decoding: the platform default (cp1252 on Windows)
                # crashes the reader thread on non-cp1252 installer output.
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=env,
            )
            output_lines: list[str] = []
            if self.progress_callback is not None:
                progress_callback = self.progress_callback
                def _read_output() -> None:
                    assert process is not None
                    assert process.stdout is not None
                    for line in process.stdout:
                        stripped = line.rstrip("\n\r")
                        output_lines.append(stripped)
                        progress_callback(stripped)  # pyright: ignore[reportOptionalCall]

                reader = threading.Thread(target=_read_output, daemon=True)
                reader.start()
                process.wait(timeout=self.timeout)
                reader.join(timeout=1)
            else:
                stdout_data, _ = process.communicate(timeout=self.timeout)
                output_lines = stdout_data.splitlines()
            returncode = process.returncode
        except subprocess.TimeoutExpired:
            if process is not None:
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
        base = self.command
        if self.platform is not None:
            override = self.platform.resolve()
            if override is not None:
                base = override
        return tuple(part.format(**context) for part in base)


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
        # Expose prior step results so downstream SelectStep/ConditionalStep can
        # branch on structured outcomes, not just exit codes (RV02). Each child
        # sees the status + outputs of every step before it under "step_results".
        statuses: dict[str, str] = {}
        for step in self.steps:
            context = {**context, "step_results": dict(outputs), "step_status": dict(statuses)}
            result = step.run(context, answers)
            outputs[step.id] = result.outputs
            statuses[step.id] = result.status
            if self.fail_fast and result.status in {"failed", "skipped", "waiting_for_input"}:
                return StepResult(
                    status=result.status,
                    outputs=outputs,
                    question=result.question,
                    reason=result.reason,
                )
        return StepResult(status="ok", outputs=outputs)


@dataclass(frozen=True)
class SelectStep:
    """Dispatch to a variant based on a runtime selector function.

    select(context) returns a key into variants. None → skipped (no variant
    matched and no fallback). Missing key with a fallback → fallback runs.
    """
    id: str
    select: Any  # Callable[[dict[str, Any]], str | None]
    variants: dict[str, Any]  # dict[str, WorkflowStep]
    fallback: Any | None = None  # WorkflowStep | None

    def plan(self, context: dict[str, Any]) -> StepResult:
        return StepResult(status="planned", reason="variant resolved at runtime")

    def run(
        self, context: dict[str, Any], answers: dict[str, WorkflowAnswer] | None = None
    ) -> StepResult:
        key = self.select(context)
        if key is not None:
            step = self.variants.get(key)
            if step is not None:
                return step.run(context, answers)
        if self.fallback is not None:
            return self.fallback.run(context, answers)
        if key is None:
            return StepResult(status="skipped", reason="no variant selected")
        return StepResult(status="failed", reason=f"no variant for key {key!r}")


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


def planned_commands(step: Any, context: dict[str, Any] | None = None) -> list[list[str]]:
    """Walk a step tree and return the shell commands it would run.

    Resolves SelectStep branches against ``context`` (falling back where no
    variant matches). Non-command steps contribute nothing.
    """
    context = context or {}
    if isinstance(step, ShellStep):
        return [step.plan(context).outputs["command"]]
    if isinstance(step, SequenceStep):
        commands: list[list[str]] = []
        for child in step.steps:
            commands.extend(planned_commands(child, context))
        return commands
    if isinstance(step, SelectStep):
        if set(step.variants) == {"run"}:
            return planned_commands(step.variants["run"], context)
        key = step.select(context)
        if key in step.variants:
            return planned_commands(step.variants[key], context)
        if step.fallback is not None:
            return planned_commands(step.fallback, context)
    return []
