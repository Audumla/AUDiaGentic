"""Managed install-baseline inventory and synchronization helpers.

See spec 50 for the required-managed/create-if-missing/generated-managed/runtime-only
contract that this inventory enforces.

The asset inventory is derived from the foundation component registry — each component
declares the files it owns. This file owns the sync logic only.
"""
from __future__ import annotations

import json
import shutil
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from audiagentic.foundation.components.base import (
    MODE_CREATE_IF_MISSING,
    MODE_GENERATED_MANAGED,
    MODE_RUNTIME_ONLY,
)
from audiagentic.paths import REPO_ROOT

DEFAULT_DOC_DIRS: tuple[str, ...] = ("specifications", "implementation", "releases", "decisions")


@dataclass(frozen=True)
class BaselineAsset:
    source: str
    target: str
    mode: str
    recursive: bool = False
    component_root: str = ""


def _iter_component_assets(component_ids: set[str] | None = None) -> Iterable[BaselineAsset]:
    from pathlib import Path

    from audiagentic.foundation.components import all_descriptors
    from audiagentic.foundation.components.base import MODE_REQUIRED_MANAGED
    from audiagentic.foundation.components.loader import register_all_components
    from audiagentic.paths import REPO_ROOT
    register_all_components()
    for descriptor in all_descriptors().values():
        if component_ids is not None and descriptor.component_id not in component_ids:
            continue
        yaml_path = descriptor.yaml_path
        if yaml_path is None:
            continue
        component_root = str(Path(yaml_path).parent / descriptor.component_id)
        for cf in descriptor.files:
            source = cf.rel_path
            asset_component_root = ""
            if cf.lifecycle == MODE_REQUIRED_MANAGED:
                stripped_source = source[len(".audiagentic/"):] if source.startswith(".audiagentic/") else source
                source_path = Path(REPO_ROOT) / component_root / stripped_source
                if source_path.exists():
                    asset_component_root = component_root
                    source = stripped_source
            yield BaselineAsset(source, cf.rel_path, cf.lifecycle, cf.recursive, asset_component_root)


def list_baseline_assets() -> list[dict[str, object]]:
    return [
        {
            "source": asset.source,
            "target": asset.target,
            "mode": asset.mode,
            "recursive": asset.recursive,
        }
        for asset in _iter_component_assets()
    ]


def ensure_project_layout(target_root: Path) -> None:
    target_root = target_root.resolve()
    docs_root = target_root / "docs"
    for subdir in DEFAULT_DOC_DIRS:
        (docs_root / subdir).mkdir(parents=True, exist_ok=True)
    audi_root = target_root / ".audiagentic"
    audi_root.mkdir(parents=True, exist_ok=True)
    (audi_root / "runtime").mkdir(parents=True, exist_ok=True)


def _iter_source_files(source_root: Path, asset: BaselineAsset) -> Iterable[tuple[Path, Path]]:
    if asset.component_root:
        component_root_path = (source_root / asset.component_root).resolve()
        source_base = component_root_path / asset.source
    else:
        source_base = source_root / asset.source
    if not source_base.exists():
        return []
    if asset.recursive:
        pairs: list[tuple[Path, Path]] = []
        for path in sorted(p for p in source_base.rglob("*") if p.is_file()):
            pairs.append((path, path.relative_to(source_base)))
        return pairs
    return [(source_base, Path(source_base.name))]


def _copy_file(source_path: Path, target_path: Path) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, target_path)


def _same_file_contents(left: Path, right: Path) -> bool:
    if not left.exists() or not right.exists():
        return False
    return left.read_bytes() == right.read_bytes()


def _append_report(report: dict, key: str, value: object) -> None:
    """Append a value to a report list, creating it if needed."""
    if key not in report:
        report[key] = []
    report[key].append(value)


def _resolve_source(source_root: Path, asset: BaselineAsset) -> Path:
    """Resolve the source path for an asset."""
    if asset.component_root:
        return (source_root / asset.component_root).resolve() / asset.source
    return source_root / asset.source


def sync_managed_baseline(
    target_root: Path,
    *,
    source_root: Path | None = None,
    component_ids: set[str] | None = None,
    lifecycle_modes: set[str] | None = None,
    refresh_overrides: bool = False,
) -> dict[str, object]:
    source_root = (source_root or REPO_ROOT).resolve()
    target_root = target_root.resolve()

    report: dict[str, object] = {
        "contract-version": "v1",
        "source-root": str(source_root),
        "target-root": str(target_root),
        "created-files": [],
        "refreshed-files": [],
        "preserved-files": [],
        "skipped-files": [],
        "excluded-paths": [],
        "warnings": [],
    }

    for asset in _iter_component_assets(component_ids):
        if asset.mode == MODE_RUNTIME_ONLY:
            _append_report(report, "excluded-paths", asset.target if asset.target.endswith("/**") else f"{asset.target}/**")
            continue
        if lifecycle_modes is not None and asset.mode not in lifecycle_modes:
            continue
        if asset.mode == MODE_GENERATED_MANAGED:
            _append_report(report, "skipped-files", {"path": asset.target, "reason": MODE_GENERATED_MANAGED})
            continue

        if asset.mode == MODE_CREATE_IF_MISSING:
            target_path = target_root / asset.target
            relative_target = asset.target.replace("\\", "/")
            if target_path.exists():
                _append_report(report, "preserved-files", relative_target)
            else:
                source_base = _resolve_source(source_root, asset)
                if source_base.exists():
                    if asset.recursive and source_base.is_dir():
                        copied = False
                        for source_path, relative_path in _iter_source_files(source_root, asset):
                            copied = True
                            nested_target = target_root / asset.target / relative_path
                            _copy_file(source_path, nested_target)
                        if not copied:
                            target_path.mkdir(parents=True, exist_ok=True)
                    elif source_base.is_dir():
                        target_path.mkdir(parents=True, exist_ok=True)
                    else:
                        _copy_file(source_base, target_path)
                else:
                    if asset.recursive:
                        target_path.mkdir(parents=True, exist_ok=True)
                    else:
                        target_path.parent.mkdir(parents=True, exist_ok=True)
                        target_path.write_text("# Installation marker\n", encoding="utf-8")
                _append_report(report, "created-files", relative_target)
            continue

        source_base = _resolve_source(source_root, asset)
        if not source_base.exists():
            _append_report(report, "warnings", f"missing source asset: {asset.source}")
            continue

        for source_path, relative_path in _iter_source_files(source_root, asset):
            if asset.recursive:
                target_path = target_root / asset.target / relative_path
                relative_target = str((Path(asset.target) / relative_path).as_posix())
            else:
                target_path = target_root / asset.target
                relative_target = asset.target.replace("\\", "/")

            if source_path.resolve() == target_path.resolve():
                _append_report(report, "skipped-files", {"path": relative_target, "reason": "source-equals-target"})
                continue

            if target_path.exists() and _same_file_contents(source_path, target_path):
                _append_report(report, "skipped-files", {"path": relative_target, "reason": "already-current"})
                continue

            if target_path.exists():
                if refresh_overrides:
                    _copy_file(source_path, target_path)
                    _append_report(report, "refreshed-files", relative_target)
                else:
                    _append_report(report, "preserved-files", relative_target)
            else:
                _copy_file(source_path, target_path)
                _append_report(report, "created-files", relative_target)

    return report


def render_sync_report(report: dict[str, object]) -> str:
    return json.dumps(report, indent=2, sort_keys=True)
