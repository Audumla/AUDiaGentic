"""Canonical step execution protocol.

All steps implement the :class:`Step` protocol with a single call signature:
``run(context) -> StepResult``.  Interactive answers live in one reserved context
field (``context["answers"]``), populated by the workflow runner — there are no
positional or keyword answer overloads.
"""
from __future__ import annotations

from typing import Any, Protocol


class Step(Protocol):
    """Execution primitive with a neutral interface."""

    id: str

    def run(self, context: dict[str, Any]) -> Any: ...

    def plan(self, context: dict[str, Any]) -> Any: ...


class CompensableStep(Step, Protocol):
    """Step that can undo its side-effects."""

    def compensate(self, context: dict[str, Any]) -> Any: ...
