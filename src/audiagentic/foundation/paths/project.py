"""Project root resolution — locate .audiagentic marker directory."""
from __future__ import annotations

import os
import time
from pathlib import Path

from audiagentic.foundation.paths.names import PROJECT_MARKER_NAME


def find_project_root(start: Path | None = None) -> Path | None:
    """Locate the project being operated on (the dir holding ``.audiagentic/``).

    Honors an explicit ``AUDIAGENTIC_REPO_ROOT`` override (needed when the
    package is installed somewhere other than the target project); otherwise
    walks up from ``start`` (default CWD) looking for the authoritative
    ``.audiagentic/`` marker. Bounded to 10 levels / 500ms so an odd mount can
    never hang the walk. Returns ``None`` if not found — callers that require a
    root raise on ``None``.
    """
    if env_root := os.environ.get("AUDIAGENTIC_REPO_ROOT"):
        return Path(env_root)
    deadline = time.monotonic() + 0.5
    current = (start or Path.cwd()).resolve()
    for _ in range(10):
        if time.monotonic() > deadline:
            break
        if (current / PROJECT_MARKER_NAME).exists():
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent
    return None
