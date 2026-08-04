from __future__ import annotations

import logging
from collections import defaultdict
from pathlib import Path
from typing import Any

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.contracts.output import ComponentOutputSink, emit_or_push_status
from audiagentic.foundation.io import atomic_write_text
from audiagentic.foundation.logging.redaction import DEFAULT_REDACT_PATTERNS

from ..descriptors.feature_mapping import KIND_SKILLS, KIND_SURFACE
from .base import SurfaceBlock, apply_managed_blocks
from .contributions import load_surface_contributions
from .registry import load_contribution_renderer_registry

logger = logging.getLogger(__name__)


def _check_surface_content(content: str) -> None:
    """Fail-closed check: reject surface content that contains secret-shaped values.

    Surfaces are git-tracked files; this prevents a secret from being committed.
    See OU01 step 5.
    """
    for pattern in DEFAULT_REDACT_PATTERNS:
        if pattern.pattern.startswith(r"(https?://"):
            continue
        if pattern.search(content):
            raise AudiaGenticError(
                code="CON-SRF-001",
                kind="providers-surfaces",
                message="Surface content contains secret-shaped value; write rejected",
            )


def _emit(output: ComponentOutputSink | None, message: str, level: str = "info", **data: Any) -> None:
    emit_or_push_status(output, "providers", message, level=level, **data)


def _active_feature_providers(project_root: Path, kind: str) -> set[str]:
    """Providers whose feature of `kind` resolves active (enabled-aware projection)."""
    from audiagentic.components.providers.services.config.feature_resolution import (
        resolve_active_provider_features,
    )

    return {
        resolved.provider_id
        for resolved in resolve_active_provider_features(project_root)
        if resolved.kind == kind
    }


def build_provider_surface_blocks(
    project_root: Path,
    *,
    provider_id: str | None = None,
) -> list[SurfaceBlock]:
    contributions = load_surface_contributions(project_root=project_root)
    renderers = load_contribution_renderer_registry()
    # Enabled-aware: writing surfaces for all providers would create redundant
    # files (CLAUDE.md, AGENTS.md, ...) for providers the user does not use. An
    # explicit provider_id is honoured as-is (caller targets that provider).
    if provider_id:
        provider_ids = [provider_id]
    else:
        provider_ids = sorted(_active_feature_providers(project_root, KIND_SURFACE) & set(renderers))
    blocks: dict[tuple[Path, str], SurfaceBlock] = {}
    for current_provider_id in provider_ids:
        renderer = renderers.get(current_provider_id)
        if renderer is None:
            continue
        try:
            for block in renderer(project_root=project_root, contributions=contributions):
                blocks.setdefault((block.path, block.block_id), block)
        except AudiaGenticError as exc:
            if exc.code.startswith("UNS-"):
                logger.debug(
                    "Skipping %s: unsupported surface feature",
                    current_provider_id,
                    extra={"provider": current_provider_id},
                )
                continue
            raise
    return sorted(blocks.values(), key=lambda item: (str(item.path), item.block_id))


def plan_provider_surfaces(
    project_root: Path,
    *,
    provider_id: str | None = None,
) -> dict[str, Any]:
    blocks = build_provider_surface_blocks(project_root, provider_id=provider_id)
    grouped: dict[Path, list[SurfaceBlock]] = defaultdict(list)
    for block in blocks:
        grouped[block.path].append(block)
    files = []
    for path, file_blocks in sorted(grouped.items(), key=lambda item: str(item[0])):
        current = path.read_text(encoding="utf-8") if path.exists() else ""
        desired = apply_managed_blocks(current, file_blocks)
        files.append(
            {
                "path": str(path),
                "block-ids": [block.block_id for block in file_blocks],
                "changed": current != desired,
            }
        )
    return {"ok": True, "files": files}



def prune_provider_surfaces(
    project_root: Path,
    *,
    provider_id: str | None = None,
    on_progress: ComponentOutputSink | None = None,
) -> dict[str, Any]:
    """Regenerate each file's managed region from active contributions.

    The region is rebuilt from the live contribution set, so blocks whose
    contribution was removed simply disappear, and files that lose all
    contributions have their region (and any legacy fences) stripped entirely.

    Generated per-tag skill files (provider skill_surface_path) are whole managed
    files with no region to strip, so a tag whose owning component is disabled or
    uninstalled would otherwise be orphaned. Those files are deleted outright when
    the tag is no longer active.

    If provider_id is given, only files owned by that provider are touched.
    """
    from .contributions import active_tag_ids

    contributions = load_surface_contributions(project_root=project_root)
    renderers = load_contribution_renderer_registry()
    provider_ids = [provider_id] if provider_id else sorted(renderers)

    _emit(on_progress, f"Pruning stale surface blocks ({len(contributions)} active contributions)")

    # Group active blocks by path (deduped, same as build_provider_surface_blocks).
    # Enabled-aware: a disabled provider renders no *active* blocks, so its managed
    # region is stripped — but its file paths stay prune candidates so the stale
    # region is actually visited and emptied.
    enabled_surface_providers = _active_feature_providers(project_root, KIND_SURFACE)
    active_by_path: dict[Path, dict[str, SurfaceBlock]] = defaultdict(dict)
    rendered_paths: set[Path] = set()
    for pid in provider_ids:
        renderer = renderers.get(pid)
        if renderer is None:
            continue
        try:
            pid_active = pid in enabled_surface_providers
            for block in renderer(project_root=project_root, contributions=contributions):
                rendered_paths.add(block.path)
                if pid_active:
                    active_by_path[block.path].setdefault(block.block_id, block)
        except AudiaGenticError as exc:
            if exc.code.startswith("UNS-"):
                _emit(on_progress, f"Skipping {pid}: unsupported surface feature", level="debug")
                continue
            raise

    candidate_paths: set[Path] = set(rendered_paths)

    from audiagentic.components.providers.descriptors.registry import all_descriptors

    descriptors = all_descriptors()
    from audiagentic.components.providers.tags.registry import all_tags

    tag_ids = sorted(all_tags())
    active_tags = active_tag_ids(project_root)
    inactive_tags = [tag_id for tag_id in tag_ids if tag_id not in active_tags]
    descriptor_ids = provider_ids if provider_id else sorted(descriptors)
    enabled_skill_providers = _active_feature_providers(project_root, KIND_SKILLS)

    # Delete generated skill files for tags whose owning component is no longer
    # active. These are whole managed files (no region to strip), so the region
    # rewrite below cannot remove them.
    deleted: list[str] = []
    for pid in descriptor_ids:
        descriptor = descriptors.get(pid)
        if descriptor is None:
            continue
        if descriptor.instruction_file:
            candidate_paths.add(project_root / descriptor.instruction_file)
        if not descriptor.skill_surface_path:
            continue
        # Enabled-aware: a disabled provider keeps no skill files (all tags removed);
        # an enabled provider keeps active-tag skills and drops inactive-tag ones.
        pid_active = pid in enabled_skill_providers
        keep_tags = active_tags if pid_active else []
        remove_tags = inactive_tags if pid_active else tag_ids
        candidate_paths.update(
            project_root / descriptor.skill_surface_path.format(tag=tag_id)
            for tag_id in keep_tags
        )
        for tag_id in remove_tags:
            skill_path = project_root / descriptor.skill_surface_path.format(tag=tag_id)
            if not skill_path.exists():
                continue
            skill_path.unlink()
            deleted.append(str(skill_path))
            reason = "tag inactive" if pid_active else "provider disabled"
            _emit(on_progress, f"Removed orphaned skill {skill_path.name} ({reason})")
            parent = skill_path.parent
            # Clean up an emptied per-tag directory (e.g. .claude/skills/<tag>/).
            if parent.name == tag_id and parent != project_root and not any(parent.iterdir()):
                parent.rmdir()

    pruned: list[str] = []
    for path in sorted(candidate_paths):
        if not path.exists():
            continue
        current = path.read_text(encoding="utf-8")
        file_blocks = list(active_by_path.get(path, {}).values())
        desired = apply_managed_blocks(current, file_blocks)
        if current == desired:
            _emit(on_progress, f"No stale blocks in {path.name}", level="debug")
            continue
        atomic_write_text(path, desired)
        pruned.append(str(path))
        _emit(on_progress, f"Pruned stale blocks from {path.name}")

    _emit(
        on_progress,
        f"Prune complete — {len(pruned)} file(s) updated, {len(deleted)} skill file(s) removed",
    )
    return {"ok": True, "pruned": pruned, "deleted": deleted}


def apply_provider_surfaces(
    project_root: Path,
    *,
    provider_id: str | None = None,
    on_progress: ComponentOutputSink | None = None,
) -> dict[str, Any]:
    scope = provider_id or "all providers"
    _emit(on_progress, f"Applying surface contributions to {scope}")
    blocks = build_provider_surface_blocks(project_root, provider_id=provider_id)
    grouped: dict[Path, list[SurfaceBlock]] = defaultdict(list)
    for block in blocks:
        grouped[block.path].append(block)
    written: list[str] = []
    for path, file_blocks in sorted(grouped.items(), key=lambda item: str(item[0])):
        current = path.read_text(encoding="utf-8") if path.exists() else ""
        desired = apply_managed_blocks(current, file_blocks)
        if current == desired:
            _emit(on_progress, f"No changes — {path.name}", level="debug")
            continue
        _check_surface_content(desired)
        atomic_write_text(path, desired)
        written.append(str(path))
        _emit(on_progress, f"Updated {path.name} ({len(file_blocks)} block(s))")
    _emit(on_progress, f"Apply complete — {len(written)} file(s) updated")
    return {"ok": True, "written": written}
