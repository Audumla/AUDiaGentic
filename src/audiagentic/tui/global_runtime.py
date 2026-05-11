"""Global runtime path resolution for the AUDiaGentic TUI."""

from __future__ import annotations

import os
from pathlib import Path


def audiagentic_home() -> Path:
    """Return the AUDiaGentic home directory.

    Override with AUDIAGENTIC_HOME env var — useful for shared/network installs.
    Default: ~/.audiagentic
    """
    custom = os.environ.get("AUDIAGENTIC_HOME")
    return Path(custom) if custom else Path.home() / ".audiagentic"


def global_harness_runtime() -> Path:
    """TUI runtime directory inside audiagentic_home()."""
    return audiagentic_home() / "harness"
