from __future__ import annotations

from pathlib import Path
from typing import Any

from ...surfaces.base import (
    SkillDefinition,
    make_single_file_contribution_renderer,
)
from ...surfaces.registry import register_contribution_renderer, register_renderer


def render(
    *,
    project_root: Path,
    syntax: dict[str, Any],
    skills: list[SkillDefinition],
    config: dict[str, Any],
) -> dict[Path, str]:
    del project_root, syntax, skills, config
    return {}


render_contributions = make_single_file_contribution_renderer("AGENTS.md")


register_renderer("openhands", render)
register_contribution_renderer("openhands", render_contributions)
