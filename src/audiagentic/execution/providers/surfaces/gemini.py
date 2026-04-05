from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import SkillDefinition, apply_managed_header, render_flat_skill, resolve_tag_path


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

    surfaces[project_root / "GEMINI.md"] = apply_managed_header(
        "# GEMINI.md\n\n"
        "This repository uses canonical prompt tags to launch AUDiaGentic workflow jobs.\n\n"
        "## Canonical rule\n\n"
        "- Do not reinterpret `@ag-plan`, `@ag-implement`, `@ag-review`, `@ag-audit`, or `@ag-check-in-prep`.\n"
        "- Route the raw tagged prompt through the repo-owned bridge instead of inventing a separate\n"
        "  workflow semantics layer.\n"
        "- Keep provenance visible: provider id, surface, and session id should survive normalization.\n\n"
        "## Bridge\n\n"
        "Use the shared prompt-trigger bridge for Gemini:\n\n"
        "```powershell\n"
        "python tools/gemini_prompt_trigger_bridge.py --project-root .\n"
        "```\n\n"
        "If a native hook path is present in the active Gemini build, it should normalize into the same\n"
        "shared launch contract. If it is not stable, the bridge stays authoritative.\n\n"
        "## Review doctrine\n\n"
        "- review prompts should stay read-focused unless the normalized request explicitly allows more\n"
        "- do not broaden review into implementation work\n"
        "- keep tracked docs and release artifacts synchronized with the job record\n"
    )
    return surfaces
