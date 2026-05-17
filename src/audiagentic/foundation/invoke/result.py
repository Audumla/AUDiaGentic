from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class InvocationResult:
    status: str                              # "ok" | "failed" | "planned" | "skipped"
    command: list[str] | None = None
    returncode: int | None = None
    stdout: str = ""
    stderr: str = ""
    reason: str | None = None
    steps: list[InvocationResult] = field(default_factory=list)
