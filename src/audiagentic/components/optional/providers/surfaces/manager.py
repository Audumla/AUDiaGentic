from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from audiagentic.foundation.contracts.output import ComponentOutputEvent, ComponentOutputSink
from audiagentic.foundation.io import atomic_write_text

from .base import SurfaceBlock, apply_managed_blocks
from .contributions import load_surface_contributions
from .registry import load_contribution_renderer_registry


def _emit(output: ComponentOutputSink | None, message: str, level: str = "info", **data: Any) -> None:
    if output is not None:
        output(ComponentOutputEvent(message=message, kind="log", level=level, data=data))


def build_provider_surface_blocks(
    project_root: Path,
    *,
    provider_id: str | None = None,
) -> list[SurfaceBlock]:
    contributions = load_surface_contributions(project_root=project_root)
    renderers = load_contribution_renderer_registry()
    provider_ids = [provider_id] if provider_id else sorted(renderers)
    blocks: dict[tuple[Path, str], SurfaceBlock] = {}
    for current_provider_id in provider_ids:
        renderer = renderers.get(current_provider_id)
        if renderer is None:
            continue
        for block in renderer(project_root=project_root, contributions=contributions):
            blocks.setdefault((block.path, block.block_id), block)
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
    active_by_path: dict[Path, dict[str, SurfaceBlock]] = defaultdict(dict)
    for pid in provider_ids:
        renderer = renderers.get(pid)
        if renderer is None:
            continue
        for block in renderer(project_root=project_root, contributions=contributions):
            active_by_path[block.path].setdefault(block.block_id, block)

    candidate_paths: set[Path] = set(active_by_path)

    from audiagentic.components.optional.providers.descriptors.registry import all_descriptors

    descriptors = all_descriptors()
    from audiagentic.components.optional.providers.tags.registry import all_tags_loaded

    tag_ids = sorted(all_tags_loaded())
    active_tags = active_tag_ids(project_root)
    inactive_tags = [tag_id for tag_id in tag_ids if tag_id not in active_tags]
    descriptor_ids = provider_ids if provider_id else sorted(descriptors)

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
        candidate_paths.update(
            project_root / descriptor.skill_surface_path.format(tag=tag_id)
            for tag_id in active_tags
        )
        for tag_id in inactive_tags:
            skill_path = project_root / descriptor.skill_surface_path.format(tag=tag_id)
            if not skill_path.exists():
                continue
            skill_path.unlink()
            deleted.append(str(skill_path))
            _emit(on_progress, f"Removed orphaned skill {skill_path.name} (tag {tag_id} inactive)")
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
        atomic_write_text(path, desired)
        written.append(str(path))
        _emit(on_progress, f"Updated {path.name} ({len(file_blocks)} block(s))")
    _emit(on_progress, f"Apply complete — {len(written)} file(s) updated")
    return {"ok": True, "written": written}
