"""Neutral result contracts for foundation execution steps."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class StepResult:
    """Outcome of one step.

    ``outputs`` is deliberately structured and redacted at the producing step
    boundary.  ``command_plan`` is intent only: it never records resolved
    credentials or subprocess output.
    """

    status: str
    outputs: dict[str, Any] = field(default_factory=dict)
    progress: list[Any] = field(default_factory=list)
    question: Any | None = None
    reason: str | None = None
    error: dict[str, Any] | None = None
    command_plan: list[list[str]] = field(default_factory=list)
    compensation: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class SequenceResult(StepResult):
    """Outcome of an ordered step sequence, including compensation details."""

    failed_step: str | None = None
