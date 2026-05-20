from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

ProgressCallback = Callable[[str], None]


@dataclass(frozen=True)
class InvocationContext:
    project_root: Path | None = None
    dry_run: bool = False
    timeout: int = 300
    on_progress: ProgressCallback | None = None
