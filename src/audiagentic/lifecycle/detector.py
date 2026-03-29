"""Installed-state detection for lifecycle operations."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

LEGACY_MARKERS = (
    Path("docs/releases/CHANGELOG.md"),
    Path("docs/releases/RELEASE_NOTES.md"),
    Path("docs/releases/VERSION_HISTORY.md"),
    Path(".github/workflows/release-please.yml"),
)

AUDIAGENTIC_MARKERS = (
    Path(".audiagentic/installed.json"),
    Path(".audiagentic/project.yaml"),
)


@dataclass(frozen=True)
class InstalledState:
    state: str
    legacy_markers: list[str]
    audiagentic_markers: list[str]


def detect_installed_state(project_root: Path) -> InstalledState:
    if not project_root.exists():
        raise FileNotFoundError(f"project root not found: {project_root}")

    legacy_hits = [str(p) for p in LEGACY_MARKERS if (project_root / p).exists()]
    audia_hits = [str(p) for p in AUDIAGENTIC_MARKERS if (project_root / p).exists()]

    if not audia_hits and not legacy_hits:
        return InstalledState("none", legacy_hits, audia_hits)
    if legacy_hits and not audia_hits and not (project_root / ".audiagentic").exists():
        return InstalledState("legacy-only", legacy_hits, audia_hits)

    audiagentic_dir = project_root / ".audiagentic"
    if not audiagentic_dir.exists():
        return InstalledState("legacy-only", legacy_hits, audia_hits)

    if legacy_hits:
        return InstalledState("mixed-or-invalid", legacy_hits, audia_hits)

    if all((project_root / marker).exists() for marker in AUDIAGENTIC_MARKERS):
        return InstalledState("audiagentic-current", legacy_hits, audia_hits)

    return InstalledState("mixed-or-invalid", legacy_hits, audia_hits)
