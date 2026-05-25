"""Installed-state detection for greenfield lifecycle operations."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from audiagentic.runtime.config import load_yaml_file

_PROJECT_MARKER = Path(".audiagentic/components/project.yaml")

AUDIAGENTIC_MARKERS = (
    _PROJECT_MARKER,
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

    if (project_root / _PROJECT_MARKER).exists():
        return InstalledState("installed", audia_hits)

    return InstalledState("invalid", audia_hits)


def get_project_version_info(project_root: Path) -> dict[str, Any] | None:
    """Read version and install timestamp from the project marker file."""
    marker = project_root / _PROJECT_MARKER
    if not marker.exists():
        return None
    try:
        data = load_yaml_file(marker)
        return {
            "version": data.get("version"),
            "installed_at": data.get("installed-at"),
        }
    except BaseException as exc:  # noqa: BLE001
        return {"error": str(exc)}
