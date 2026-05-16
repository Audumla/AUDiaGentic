from __future__ import annotations

import os
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any

from .base import SurfaceBlock, apply_managed_blocks
from .contributions import load_surface_contributions
from .registry import load_contribution_renderer_registry


def build_provider_surface_blocks(
    project_root: Path,
    *,
    provider_id: str | None = None,
) -> list[SurfaceBlock]:
    contributions = load_surface_contributions()
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


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=path.stem + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def apply_provider_surfaces(
    project_root: Path,
    *,
    provider_id: str | None = None,
) -> dict[str, Any]:
    blocks = build_provider_surface_blocks(project_root, provider_id=provider_id)
    grouped: dict[Path, list[SurfaceBlock]] = defaultdict(list)
    for block in blocks:
        grouped[block.path].append(block)
    written: list[str] = []
    for path, file_blocks in sorted(grouped.items(), key=lambda item: str(item[0])):
        current = path.read_text(encoding="utf-8") if path.exists() else ""
        desired = apply_managed_blocks(current, file_blocks)
        if current == desired:
            continue
        _write_atomic(path, desired)
        written.append(str(path))
    return {"ok": True, "written": written}
