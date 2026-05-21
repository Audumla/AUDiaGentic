from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from audiagentic.foundation.output import ComponentOutputEvent, ComponentOutputSink

ProgressCallback = ComponentOutputSink


@dataclass(frozen=True)
class InvocationContext:
    project_root: Path | None = None
    dry_run: bool = False
    timeout: int = 300
    on_progress: ProgressCallback | None = None

    def progress(self, message: str, *, progress: float | None = None, total: float | None = None) -> None:
        if self.on_progress is not None:
            self.on_progress(ComponentOutputEvent(message=message, progress=progress, total=total))
