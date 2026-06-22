from __future__ import annotations

from pathlib import Path
from typing import Any

from ...surfaces.base import (
    SkillDefinition,
    make_single_file_contribution_renderer,
    render_frontmatter_skill,
    resolve_tag_path,
)
from ...surfaces.registry import register_contribution_renderer, register_renderer

render_contributions = make_single_file_contribution_renderer("AGENTS.md")


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


register_renderer("aider", render)
register_contribution_renderer("aider", render_contributions)
