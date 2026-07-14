from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from audiagentic.foundation.steps.control import (
    WorkflowAnswer,
    WorkflowQuestion,
)


@dataclass(frozen=True)
class WorkflowProgress:
    message: str
    step_id: str | None = None
    level: str = "info"
    progress: float | None = None
    total: float | None = None
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkflowInvocationResult:
    status: str
    outputs: dict[str, Any] = field(default_factory=dict)
    progress: list[WorkflowProgress] = field(default_factory=list)
    question: WorkflowQuestion | None = None
    failed_step: str | None = None
    reason: str | None = None
