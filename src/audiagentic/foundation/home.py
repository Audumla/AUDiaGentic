from __future__ import annotations

import os
from pathlib import Path


def audiagentic_home() -> Path:
    """Return the shared AUDiaGentic root directory."""
    custom = os.environ.get("AUDIAGENTIC_HOME")
    return Path(custom) if custom else Path.home() / ".audiagentic"


def global_harness_runtime() -> Path:
    """Return the harness runtime directory."""
    return audiagentic_home() / "harness"


def global_log_dir(component: str) -> Path:
    """Return the global log directory for a named component."""
    return audiagentic_home() / "logs" / component


def project_log_dir(project_root: Path, component: str) -> Path:
    """Return the project-scoped log directory for a named component."""
    return project_root / ".audiagentic" / "logs" / component
