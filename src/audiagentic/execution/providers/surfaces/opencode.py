from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import SkillDefinition, apply_managed_header, render_frontmatter_skill, resolve_tag_path


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
        surfaces[path] = apply_managed_header(
            render_frontmatter_skill(skill, root_label=path_template.format(tag=skill.tag))
        )
    return surfaces
