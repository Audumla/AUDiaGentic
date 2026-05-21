from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from audiagentic.paths import SRC_ROOT

from .base import SurfaceContribution

_CONFIG_ROOT = SRC_ROOT / "audiagentic" / "config"


def _as_strings(raw: Any) -> tuple[str, ...]:
    if not isinstance(raw, list):
        return ()
    return tuple(item for item in raw if isinstance(item, str) and item)


def _contributions_from_data(data: dict[str, Any], component_id: str) -> list[SurfaceContribution]:
    contributions: list[SurfaceContribution] = []
    for raw in data.get("surface-contributions") or []:
        if not isinstance(raw, dict):
            continue
        content = raw.get("content") or {}
        body = content.get("body") if isinstance(content, dict) else raw.get("body")
        if not isinstance(body, str):
            continue
        contribution_id = raw.get("id")
        kind = raw.get("kind")
        title = raw.get("title") or raw.get("summary")
        if not all(isinstance(item, str) and item for item in (contribution_id, kind, title)):
            continue
        contributions.append(
            SurfaceContribution(
                contribution_id=contribution_id,
                owner_component=raw.get("owner") if isinstance(raw.get("owner"), str) else component_id,
                kind=kind,
                title=title,
                body=body,
                preferred_targets=_as_strings(raw.get("preferred-targets")),
            )
        )
    return contributions


def load_tag_surface_contributions() -> list[SurfaceContribution]:
    """Load surface contributions declared in each tag's descriptor.yaml."""
    from audiagentic.components.optional.providers.tags.registry import (  # noqa: PLC0415
        all_tags_loaded,
    )
    contributions: list[SurfaceContribution] = []
    for tag_id, descriptor in sorted(all_tags_loaded().items()):
        for contrib in descriptor.surface_contributions:
            contributions.append(
                SurfaceContribution(
                    contribution_id=contrib.contribution_id,
                    owner_component=f"prompt-trigger-tag:{tag_id}",
                    kind=contrib.kind,
                    title=contrib.title,
                    body=contrib.body,
                    preferred_targets=contrib.preferred_targets,
                )
            )
    return contributions


def _build_canonical_tags_body(tags: dict) -> str:
    """Build the canonical-tags summary block body from all loaded tags."""
    lines = ["Canonical tags:\n"]
    for tag_id in sorted(tags):
        descriptor = tags[tag_id]
        alias_sample = ", ".join(f"`{a}`" for a in list(descriptor.aliases)[:2])
        alias_note = f" (aliases: {alias_sample})" if alias_sample else ""
        lines.append(f"- `{tag_id}`{alias_note}")
    lines += [
        "",
        "Rules:",
        "",
        "- Do not reinterpret these tags — route the raw tagged prompt through the repo-owned bridge.",
        "- Keep tag semantics identical to the shared AUDiaGentic launch contract.",
        "- Keep provenance visible: provider id, surface, and session id should survive normalization.",
        "- Tag definitions are managed in `config/prompt-triggers/tags/`;",
        "  run `python -m audiagentic.components.optional.providers.skill_surfaces --project-root .`"
        " after adding, removing, or renaming tags.",
    ]
    return "\n".join(lines) + "\n"


def _build_tag_shortcuts_body(tags: dict) -> str:
    """Build the aliases cheatsheet body from all loaded tags."""
    lines = [
        "Tag and provider aliases are centralized in the tag registry and",
        "`config/prompt-triggers/tags/` and work in all surfaces.\n",
        "Tag aliases:\n",
    ]
    for tag_id in sorted(tags):
        descriptor = tags[tag_id]
        for alias in descriptor.aliases:
            lines.append(f"- `{alias}` -> `{tag_id}`")
    lines += [
        "",
        "Provider aliases:\n",
        "- `cx` -> `codex`",
        "- `cld` -> `claude`",
        "- `cln` -> `cline`",
        "- `gm` -> `gemini`",
        "- `opc` -> `opencode`",
        "- `cp` -> `copilot`",
    ]
    return "\n".join(lines) + "\n"


def build_summary_contributions() -> list[SurfaceContribution]:
    """Build synthetic cross-tag summary contributions.

    These replace the old hardcoded agent-jobs/canonical-rule and
    agent-jobs/tag-shortcuts blocks. Generated dynamically from all
    loaded tag descriptors so they stay accurate without manual edits.
    """
    from audiagentic.components.optional.providers.tags.registry import (  # noqa: PLC0415
        all_tags_loaded,
    )
    tags = all_tags_loaded()
    if not tags:
        return []
    return [
        SurfaceContribution(
            contribution_id="agent-jobs/canonical-rule",
            owner_component="agent-jobs",
            kind="rule",
            title="Canonical workflow tags",
            body=_build_canonical_tags_body(tags),
        ),
        SurfaceContribution(
            contribution_id="agent-jobs/tag-shortcuts",
            owner_component="agent-jobs",
            kind="rule",
            title="Tag shortcuts and aliases",
            body=_build_tag_shortcuts_body(tags),
        ),
    ]


def load_surface_contributions(config_root: Path | None = None) -> list[SurfaceContribution]:
    from audiagentic.foundation.components.loader import register_all_components
    from audiagentic.foundation.components.registry import all_descriptors

    register_all_components()
    root = (config_root or _CONFIG_ROOT).resolve()

    # Component-level contributions (from YAML config files)
    contributions: list[SurfaceContribution] = []
    for descriptor in sorted(all_descriptors().values(), key=lambda d: d.component_id):
        if not descriptor.config_path:
            continue
        config_file = root / descriptor.config_path
        if not config_file.exists():
            continue
        data = yaml.safe_load(config_file.read_text(encoding="utf-8")) or {}
        contributions.extend(_contributions_from_data(data, descriptor.component_id))

    # Per-tag contributions from tag descriptors
    contributions.extend(load_tag_surface_contributions())

    # Synthetic cross-tag summaries (canonical list + aliases cheatsheet)
    contributions.extend(build_summary_contributions())

    return contributions
