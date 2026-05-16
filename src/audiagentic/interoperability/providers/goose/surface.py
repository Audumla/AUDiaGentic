from __future__ import annotations

from pathlib import Path
from typing import Any

from ..surfaces.base import SkillDefinition, SurfaceBlock, SurfaceContribution
from ..surfaces.registry import register_contribution_renderer, register_renderer


def render(
    *,
    project_root: Path,
    syntax: dict[str, Any],
    skills: list[SkillDefinition],
    config: dict[str, Any],
) -> dict[Path, str]:
    del project_root, syntax, skills, config
    return {}


def render_contributions(
    *,
    project_root: Path,
    contributions: list[SurfaceContribution],
) -> list[SurfaceBlock]:
    return [
        SurfaceBlock(
            path=project_root / "AGENTS.md",
            block_id=contribution.contribution_id,
            content=f"## {contribution.title}\n\n{contribution.body.strip()}",
        )
        for contribution in contributions
        if contribution.kind == "rule"
    ]


register_renderer("goose", render)
register_contribution_renderer("goose", render_contributions)
