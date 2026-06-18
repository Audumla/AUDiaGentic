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


def active_tag_ids(project_root: Path | None = None) -> set[str]:
    """Return the set of tag ids whose owning component is installed and enabled.

    A tag is owned by the component that declared it (ActionDescriptor.owner_component_id).
    With no project_root the install/enable state is unknown, so every loaded tag is
    treated as active. Tags with an empty/unknown owner are also treated as active so
    that ownership-unaware callers keep working.
    """
    from audiagentic.components.optional.providers.tags.registry import (  # noqa: PLC0415
        all_tags_loaded,
    )
    from audiagentic.foundation.components.registry import is_enabled, is_installed  # noqa: PLC0415

    tags = all_tags_loaded()
    if project_root is None:
        return set(tags)
    active: set[str] = set()
    for tag_id, descriptor in tags.items():
        owner = descriptor.owner_component_id
        if not owner or (is_installed(owner, project_root) and is_enabled(owner, project_root)):
            active.add(tag_id)
    return active


def load_tag_surface_contributions(project_root: Path | None = None) -> list[SurfaceContribution]:
    """Load surface contributions declared in each tag's descriptor.yaml.

    A tag's contributions are included only while its owning component is installed and
    enabled (see active_tag_ids). With no project_root, all loaded tags contribute.
    """
    from audiagentic.components.optional.providers.tags.registry import (  # noqa: PLC0415
        all_tags_loaded,
    )

    active = active_tag_ids(project_root)
    contributions: list[SurfaceContribution] = []
    for tag_id, descriptor in sorted(all_tags_loaded().items()):
        if tag_id not in active:
            continue
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


_OVERVIEW_BODY = (
    "This repository uses AUDiaGentic workflow jobs. The instruction blocks below "
    "are generated from component sources — do not edit them directly; edit the "
    "owning component config and re-run surface apply.\n"
)


def _build_canonical_tags_body(tags: dict) -> str:
    """Build the canonical-tags summary block body from all loaded tags.

    Tag-routing doctrine lives in the agent-jobs/prompt-tags block; this block is
    just the canonical tag list plus where definitions are managed.
    """
    lines = ["Canonical tags (route the raw tagged prompt through the repo-owned bridge):\n"]
    for tag_id in sorted(tags):
        descriptor = tags[tag_id]
        alias_sample = ", ".join(f"`{a}`" for a in list(descriptor.aliases)[:2])
        alias_note = f" (aliases: {alias_sample})" if alias_sample else ""
        lines.append(f"- `{tag_id}`{alias_note}")
    lines += [
        "",
        "Definitions are managed in `config/components/optional/agent-jobs/tags/`; run"
        " `python -m audiagentic.components.optional.providers.skill_surfaces --project-root .`"
        " after adding, removing, or renaming tags.",
    ]
    return "\n".join(lines) + "\n"


def build_summary_contributions(project_root: Path | None = None) -> list[SurfaceContribution]:
    """Build synthetic cross-tag summary contributions.

    Generates the managed preamble and the canonical-tags list dynamically from
    all loaded tag descriptors so they stay accurate without manual edits. The
    canonical-rule documents every valid tag regardless of per-tag install state.
    Tag-routing doctrine is owned by the agent-jobs/prompt-tags block and is not
    duplicated here; alias tables live in the tag registry, not the surfaces.
    """
    from audiagentic.components.optional.providers.tags.registry import (  # noqa: PLC0415
        all_tags_loaded,
    )

    tags = all_tags_loaded()
    if not tags:
        return []
    return [
        SurfaceContribution(
            contribution_id="agent-jobs/overview",
            owner_component=COMPONENT_AGENT_JOBS,
            title="AUDiaGentic agent instructions",
            body=_OVERVIEW_BODY,
        ),
        SurfaceContribution(
            contribution_id="agent-jobs/canonical-rule",
            owner_component=COMPONENT_AGENT_JOBS,
            title="Canonical workflow tags",
            body=_build_canonical_tags_body(tags),
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
