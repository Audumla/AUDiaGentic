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
    surfaces: dict[Path, str] = {}
    path_template = str(config["path"])
    for skill in skills:
        path = resolve_tag_path(project_root, path_template, skill.tag)
        surfaces[path] = render_frontmatter_skill(skill, root_label=path_template.format(tag=skill.tag))
    return surfaces


register_renderer("opencode", render)
register_contribution_renderer("opencode", render_contributions)
