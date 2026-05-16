from __future__ import annotations

from pathlib import Path
from typing import Any

from ..surfaces.base import (
    SkillDefinition,
    SurfaceBlock,
    SurfaceContribution,
    render_frontmatter_skill,
    resolve_tag_path,
)
from ..surfaces.registry import register_contribution_renderer, register_renderer


def render(
    *,
    project_root: Path,
    syntax: dict[str, Any],
    skills: list[SkillDefinition],
    config: dict[str, Any],
) -> dict[Path, str]:
    del syntax
    path_template = str(config.get("path", ".aider/skills/{tag}.md"))
    return {
        resolve_tag_path(project_root, path_template, skill.tag): render_frontmatter_skill(
            skill, root_label=path_template.format(tag=skill.tag)
        )
        for skill in skills
    }


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


register_renderer("aider", render)
register_contribution_renderer("aider", render_contributions)
