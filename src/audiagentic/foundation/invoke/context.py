from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class InvocationContext:
    project_root: Path | None = None
    dry_run: bool = False
    timeout: int = 300
