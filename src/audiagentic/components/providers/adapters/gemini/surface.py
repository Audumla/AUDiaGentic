from __future__ import annotations

from pathlib import Path
from typing import Any

from ...surfaces.base import (
    SkillDefinition,
    apply_managed_header,
    make_single_file_contribution_renderer,
    render_flat_skill,
    render_instruction_file,
    resolve_tag_path,
)
from ...surfaces.registry import register_contribution_renderer, register_renderer

_ADAPTER_DIR = Path(__file__).parent

render_contributions = make_single_file_contribution_renderer("GEMINI.md")


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
            render_flat_skill(
                skill,
                provider_name="gemini",
                launch_example=f"@{skill.tag}-gemini",
            )
        )

    surfaces[project_root / "GEMINI.md"] = render_instruction_file(
        provider_id="gemini",
        instruction_file="GEMINI.md",
        adapter_dir=_ADAPTER_DIR,
    )
    return surfaces


register_renderer("gemini", render)
register_contribution_renderer("gemini", render_contributions)
