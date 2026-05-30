from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from audiagentic.foundation.components.ids import COMPONENT_AGENT_JOBS

from .base import SurfaceContribution


def _as_strings(raw: Any) -> tuple[str, ...]:
    if not isinstance(raw, list):
        return ()
    return tuple(item for item in raw if isinstance(item, str) and item)


def _contributions_from_data(data: dict[str, Any], component_id: str) -> list[SurfaceContribution]:
    # Unified `contributions:` key; fall back to legacy `surface-contributions:`.
    raw_list = data.get("contributions") or data.get("surface-contributions") or []
    contributions: list[SurfaceContribution] = []
    for raw in raw_list:
        if not isinstance(raw, dict):
            continue
        # Skip file references — those are action files handled by the tag loader.
        if "config" in raw:
            continue
        content = raw.get("content") or {}
        body = content.get("body") if isinstance(content, dict) else raw.get("body")
        if not isinstance(body, str):
            continue
        contribution_id = raw.get("id")
        title = raw.get("title") or raw.get("summary")
        if not all(isinstance(item, str) and item for item in (contribution_id, title)):
            continue
        contributions.append(
            SurfaceContribution(
                contribution_id=contribution_id,
                owner_component=raw.get("owner") if isinstance(raw.get("owner"), str) else component_id,
                title=title,
                body=body,
                preferred_targets=_as_strings(raw.get("preferred-targets")),
            )
        )
    return contributions


def load_tag_surface_contributions(project_root: Path | None = None) -> list[SurfaceContribution]:
    """Load surface contributions declared in each tag's descriptor.yaml.

    Tags are optional parts of the agent-jobs component, not separate components.
    If project_root is given, contributions are only included when agent-jobs is installed and enabled.
    """
    from audiagentic.components.optional.providers.tags.registry import (  # noqa: PLC0415
        all_tags_loaded,
    )
    from audiagentic.foundation.components.registry import is_enabled, is_installed  # noqa: PLC0415

    if project_root is not None and not (
        is_installed(COMPONENT_AGENT_JOBS, project_root)
        and is_enabled(COMPONENT_AGENT_JOBS, project_root)
    ):
        return []

    contributions: list[SurfaceContribution] = []
    for tag_id, descriptor in sorted(all_tags_loaded().items()):
        for contrib in descriptor.instructions:
            contributions.append(
                SurfaceContribution(
                    contribution_id=contrib.contribution_id,
                    owner_component=f"action:{tag_id}",
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
        "- Tag definitions are managed in `config/components/optional/agent-jobs/tags/`;",
        "  run `python -m audiagentic.components.optional.providers.skill_surfaces --project-root .`"
        " after adding, removing, or renaming tags.",
    ]
    return "\n".join(lines) + "\n"


def _build_tag_shortcuts_body(tags: dict) -> str:
    """Build the aliases cheatsheet body from all loaded tags."""
    lines = [
        "Tag and provider aliases are centralized in the tag registry and",
        "`config/components/optional/agent-jobs/tags/` and work in all surfaces.\n",
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


def build_summary_contributions(project_root: Path | None = None) -> list[SurfaceContribution]:
    """Build synthetic cross-tag summary contributions.

    These replace the old hardcoded agent-jobs/canonical-rule and
    agent-jobs/tag-shortcuts blocks. Generated dynamically from all
    loaded tag descriptors so they stay accurate without manual edits.

    Always uses all registered tags — the canonical-rule is a routing contract
    that documents every valid tag regardless of per-tag installation state.
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
            owner_component=COMPONENT_AGENT_JOBS,
            title="Canonical workflow tags",
            body=_build_canonical_tags_body(tags),
        ),
        SurfaceContribution(
            contribution_id="agent-jobs/tag-shortcuts",
            owner_component=COMPONENT_AGENT_JOBS,
            title="Tag shortcuts and aliases",
            body=_build_tag_shortcuts_body(tags),
        ),
    ]


def load_surface_contributions(
    project_root: Path | None = None,
) -> list[SurfaceContribution]:
    from audiagentic.foundation.components.loader import register_all_components
    from audiagentic.foundation.components.registry import all_descriptors, is_enabled, is_installed

    register_all_components()

    # Component-level contributions (from each component's YAML file)
    contributions: list[SurfaceContribution] = []
    for descriptor in sorted(all_descriptors().values(), key=lambda d: d.component_id):
        if not descriptor.yaml_path or not descriptor.yaml_path.exists():
            continue
        # Only include contributions from installed+enabled components.
        # Core components always contribute (they cannot be uninstalled).
        if project_root is not None and not descriptor.core:
            if not is_installed(descriptor.component_id, project_root):
                continue
            if not is_enabled(descriptor.component_id, project_root):
                continue
        data = yaml.safe_load(descriptor.yaml_path.read_text(encoding="utf-8")) or {}
        contributions.extend(_contributions_from_data(data, descriptor.component_id))

    # Per-tag contributions from tag descriptors
    contributions.extend(load_tag_surface_contributions(project_root=project_root))

    # Synthetic cross-tag summaries — only if agent-jobs component is installed+enabled
    if project_root is None or (
        is_installed("agent-jobs", project_root) and is_enabled("agent-jobs", project_root)
    ):
        contributions.extend(build_summary_contributions(project_root=project_root))

    return contributions
