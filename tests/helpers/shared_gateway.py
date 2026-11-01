"""Helpers for shared-gateway test configuration."""
from __future__ import annotations

from pathlib import Path


def declare_project(root: Path, project_id: str) -> Path:
    """Create ``root`` and declare ``project.id`` in its tracked settings, as a served project needs."""
    settings = root / ".audiagentic" / "settings.yaml"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(f"schema_version: 1\nproject:\n  id: {project_id}\n", encoding="utf-8")
    return root
