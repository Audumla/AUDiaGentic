"""Interactive workflow step vocabulary.

Confirm, Select, and Conditional steps live here so they are available from
the canonical ``foundation.steps`` package.  All use the neutral
``run(context)`` protocol; interactive answers arrive in
``context.get("answers")`` as a dict[str, WorkflowAnswer].
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from .results import StepResult


@dataclass(frozen=True)
class WorkflowAnswer:
    question_id: str
    value: Any


@dataclass(frozen=True)
class WorkflowQuestion:
    id: str
    prompt: str
    kind: str = "confirm"
    options: list[dict[str, str]] = None  # type: ignore[assignment]
    default: str | None = None
    metadata: dict[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.options is None:
            object.__setattr__(self, "options", [])
        if self.metadata is None:
            object.__setattr__(self, "metadata", {})


class Step(Protocol):
    id: str

    def run(self, context: dict[str, Any]) -> StepResult: ...

    def plan(self, context: dict[str, Any]) -> StepResult: ...


@dataclass(frozen=True)
class ConfirmStep:
    id: str
    prompt: str
    default: str = "yes"
    metadata: dict[str, Any] | None = None

    def plan(self, context: dict[str, Any]) -> StepResult:
        return StepResult(status="planned")

    def run(self, context: dict[str, Any], answers: dict[str, WorkflowAnswer] | None = None) -> StepResult:
        merged = {**(context.get("answers") or {}), **(answers or {})}
        answer = merged.get(self.id)
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
class SelectStep:
    """Dispatch to a variant based on a runtime selector function.

    select(context) returns a key into variants. None -> skipped (no variant
    matched and no fallback). Missing key with a fallback -> fallback runs.
    """
    id: str
    select: Any  # Callable[[dict[str, Any]], str | None]
    variants: dict[str, Any]  # dict[str, Step]
    fallback: Any | None = None  # Step | None

    def plan(self, context: dict[str, Any]) -> StepResult:
        return StepResult(status="planned", reason="variant resolved at runtime")

    def run(self, context: dict[str, Any]) -> StepResult:
        key = self.select(context)
        if key is not None:
            step = self.variants.get(key)
            if step is not None:
                return step.run(context)
        if self.fallback is not None:
            return self.fallback.run(context)
        if key is None:
            return StepResult(status="skipped", reason="no variant selected")
        return StepResult(status="failed", reason=f"no variant for key {key!r}")


@dataclass(frozen=True)
class ConditionalStep:
    id: str
    condition_key: str
    when_true: Step
    when_false: Step | None = None

    def plan(self, context: dict[str, Any]) -> StepResult:
        return StepResult(status="planned", reason="conditional branch resolved at runtime")

    def run(self, context: dict[str, Any]) -> StepResult:
        if bool(context.get(self.condition_key)):
            return self.when_true.run(context)
        if self.when_false is not None:
            return self.when_false.run(context)
        return StepResult(status="skipped", reason="condition not met")


def planned_commands(step: Any, context: dict[str, Any] | None = None) -> list[list[str]]:
    """Walk a step tree and return the shell commands it would run."""
    context = context or {}
    from .sequence import SequenceStep
    from .shell import ShellStep

    if isinstance(step, ShellStep):
        result = step.plan(context)
        cmd = result.outputs.get("command")
        if not cmd:
            return []
        if not isinstance(cmd, list) or not all(isinstance(part, str) for part in cmd):
            raise TypeError("ShellStep plan command must be a list of strings")
        return [cmd]
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
