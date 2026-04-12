from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import (
    SkillDefinition,
    apply_managed_header,
    canonical_tags,
    provider_alias_examples,
    render_flat_skill,
    resolve_tag_path,
    tag_alias_examples,
)


def render(
    *,
    project_root: Path,
    syntax: dict[str, Any],
    skills: list[SkillDefinition],
    config: dict[str, Any],
) -> dict[Path, str]:
    surfaces: dict[Path, str] = {}
    path_template = str(config["path"])
    for skill in skills:
        path = resolve_tag_path(project_root, path_template, skill.tag)
        surfaces[path] = apply_managed_header(
            render_flat_skill(
                skill,
                provider_name="cline",
                launch_example=f"@{skill.tag}-cline",
            )
        )

    surfaces[project_root / ".clinerules" / "prompt-tags.md"] = apply_managed_header(
        "# Prompt tag doctrine\n\n"
        "Canonical tags:\n\n"
        + "\n".join(f"- `@{tag}`" for tag in canonical_tags(syntax))
        + "\n\nRules:\n\n"
        "- parse only the first non-empty line for the canonical tag\n"
        "- keep tag semantics identical to the shared AUDiaGentic launch contract\n"
        "- do not invent provider-specific alternate tags\n"
        "- preserve raw prompt text in provenance metadata\n"
        "- route tagged prompts through the shared bridge when a native hook path is not stable\n"
        "- canonical names are config-managed in `.audiagentic/prompt-syntax.yaml`; run\n"
        "  `python tools/regenerate_tag_surfaces.py --project-root .` after renaming tags or aliases\n\n"
        "## Tag aliases and shortcuts\n\n"
        "Centralized in `.audiagentic/prompt-syntax.yaml`. All of these are equivalent:\n\n"
        + "\n".join(tag_alias_examples(syntax))
        + "\n\n"
        + "\n".join(provider_alias_examples(syntax))
        + "\n\nUse shortcuts for brevity:\n\n"
        "```text\n"
        "@agr-cln target=packet:PKT-PRV-033\n"
        "Review the implementation status.\n"
        "```\n"
    )
    return surfaces
