"""Installed-state detection for greenfield lifecycle operations."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

_CORE_LIFECYCLE_MARKER = Path(".audiagentic/components/core-lifecycle.yaml")

AUDIAGENTIC_MARKERS = (
    _CORE_LIFECYCLE_MARKER,
)


@dataclass(frozen=True)
class InstalledState:
    state: str
    audiagentic_markers: list[str]


def detect_installed_state(project_root: Path) -> InstalledState:
    if not project_root.exists():
        raise FileNotFoundError(f"project root not found: {project_root}")

    audia_hits = [str(p) for p in AUDIAGENTIC_MARKERS if (project_root / p).exists()]

    if not audia_hits and not (project_root / ".audiagentic").exists():
        return InstalledState("none", audia_hits)

    audiagentic_dir = project_root / ".audiagentic"
    if not audiagentic_dir.exists():
        return InstalledState("none", audia_hits)

    if (project_root / _CORE_LIFECYCLE_MARKER).exists():
        return InstalledState("installed", audia_hits)

    return InstalledState("invalid", audia_hits)
