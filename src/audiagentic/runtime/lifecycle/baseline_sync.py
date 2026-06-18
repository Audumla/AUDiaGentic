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

import yaml

from audiagentic.foundation.components.base import (
    MODE_CREATE_IF_MISSING,
    MODE_GENERATED_MANAGED,
    MODE_RUNTIME_ONLY,
)
from audiagentic.foundation.io import atomic_write_text
from audiagentic.paths import REPO_ROOT

DEFAULT_DOC_DIRS: tuple[str, ...] = ("specifications", "implementation", "releases", "decisions")


@dataclass(frozen=True)
class BaselineAsset:
    source: str
    target: str
    mode: str
    recursive: bool = False


def _iter_component_assets(component_ids: set[str] | None = None) -> Iterable[BaselineAsset]:
    from audiagentic.foundation.components import all_descriptors
    from audiagentic.foundation.components.loader import register_all_components
    register_all_components()
    for descriptor in all_descriptors().values():
        if component_ids is not None and descriptor.component_id not in component_ids:
            continue
        for cf in descriptor.files:
            yield BaselineAsset(cf.rel_path, cf.rel_path, cf.lifecycle, cf.recursive)


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


def _default_prompt_syntax_yaml() -> str:
    from audiagentic.components.optional.agent_jobs.prompt_syntax import _build_default_syntax

    payload = _build_default_syntax()
    return yaml.safe_dump(payload, sort_keys=False, allow_unicode=False)


def _default_project_config_yaml() -> str:
    payload = {
        "contract-version": "v1",
        "project-id": "audia-example",
        "project-name": "AUDiaGentic Example",
        "workflow-profile": "standard",
        "tracked-docs-root": "docs",
        "runtime-root": ".audiagentic/runtime",
        "release-strategy": "release-please",
        "prompt-launch": {"syntax": "prefix-token-v1"},
    }
    return yaml.safe_dump(payload, sort_keys=False, allow_unicode=False)


def _release_workflow_yaml() -> str:
    from audiagentic.components.optional.release.release_please.install import _render

    return _render("release.yml", {"__BRANCH__": "main", "__PYTHON_VERSION__": "3.13"})


def _component_skill_yaml(component_id: str, title: str, body: str) -> str:
    return (
        "---\n"
        f"name: {component_id}\n"
        f"description: {title}\n"
        "---\n\n"
        f"# {title}\n\n"
        "Do:\n"
        f"- {body.strip()}\n\n"
        "Do not:\n"
        "- broaden scope beyond the tagged request\n"
    )


def _iter_component_skill_assets() -> Iterable[tuple[str, str]]:
    from audiagentic.components.optional.providers.surfaces.contributions import (
        load_surface_contributions,
    )

    for contribution in load_surface_contributions(project_root=None):
        if contribution.contribution_id == "agent-ledger/process":
            yield (
                ".audiagentic/skills/ag-ledger/skill.md",
                _component_skill_yaml("ag-ledger", "Agent ledger", contribution.body),
            )
        elif contribution.contribution_id == "release/doctrine":
            yield (
                ".audiagentic/skills/ag-check-in-prep/skill.md",
                _component_skill_yaml("ag-check-in-prep", "Check-in prep", contribution.body),
            )


def _iter_prompt_template_assets() -> Iterable[tuple[str, str]]:
    from audiagentic.components.optional.providers.tags.registry import all_tags_loaded

    for tag_id, descriptor in sorted(all_tags_loaded().items()):
        for prompt in descriptor.prompts:
            source = descriptor.config_dir / prompt.content_file
            if source.exists():
                content = source.read_text(encoding="utf-8")
            else:
                bodies = [instruction.body.strip() for instruction in descriptor.instructions if instruction.body.strip()]
                content = "\n\n".join(bodies) or descriptor.description or f"{descriptor.display_name} prompt"
                content = content.rstrip() + "\n"
            yield f".audiagentic/prompts/{tag_id}/{prompt.name}.md", content


def _write_virtual_file(
    target_root: Path,
    relative_target: str,
    content: str,
    report: dict[str, object],
) -> None:
    target_path = target_root / relative_target
    existed = target_path.exists()
    current = target_path.read_text(encoding="utf-8") if existed else None
    if current == content:
        skipped = report["skipped-files"]
        assert isinstance(skipped, list)
        skipped.append({"path": relative_target, "reason": "already-current"})
        return
    atomic_write_text(target_path, content)
    bucket = "refreshed-files" if existed else "created-files"
    entries = report[bucket]
    assert isinstance(entries, list)
    entries.append(relative_target)


def _sync_virtual_asset(
    asset: BaselineAsset,
    target_root: Path,
    report: dict[str, object],
) -> bool:
    if asset.target == ".audiagentic/config/execution/prompt-syntax.yaml":
        target_path = target_root / asset.target
        if target_path.exists() and asset.mode == MODE_CREATE_IF_MISSING:
            preserved = report["preserved-files"]
            assert isinstance(preserved, list)
            preserved.append(asset.target)
            return True
        _write_virtual_file(target_root, asset.target, _default_prompt_syntax_yaml(), report)
        return True

    if asset.target == ".audiagentic/config/project.yaml":
        target_path = target_root / asset.target
        if target_path.exists() and asset.mode == MODE_CREATE_IF_MISSING:
            preserved = report["preserved-files"]
            assert isinstance(preserved, list)
            preserved.append(asset.target)
            return True
        _write_virtual_file(target_root, asset.target, _default_project_config_yaml(), report)
        return True

    if asset.target == ".audiagentic/prompts":
        for relative_target, content in _iter_prompt_template_assets():
            _write_virtual_file(target_root, relative_target, content, report)
        return True

    if asset.target == ".audiagentic/skills/ag-ledger/skill.md":
        for relative_target, content in _iter_component_skill_assets():
            if relative_target == asset.target:
                _write_virtual_file(target_root, relative_target, content, report)
                return True

    if asset.target == ".audiagentic/skills/ag-check-in-prep/skill.md":
        for relative_target, content in _iter_component_skill_assets():
            if relative_target == asset.target:
                _write_virtual_file(target_root, relative_target, content, report)
                return True

    if asset.target == ".github/workflows/release.yml":
        _write_virtual_file(target_root, asset.target, _release_workflow_yaml(), report)
        return True

    return False


def sync_managed_baseline(
    target_root: Path,
    *,
    source_root: Path | None = None,
    component_ids: set[str] | None = None,
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
            cast = report["excluded-paths"]
            assert isinstance(cast, list)
            cast.append(asset.target if asset.target.endswith("/**") else f"{asset.target}/**")
            continue
        if asset.mode == MODE_GENERATED_MANAGED:
            cast = report["skipped-files"]
            assert isinstance(cast, list)
            cast.append({"path": asset.target, "reason": MODE_GENERATED_MANAGED})
            continue

        if _sync_virtual_asset(asset, target_root, report):
            continue

        if asset.mode == MODE_CREATE_IF_MISSING:
            target_path = target_root / asset.target
            relative_target = asset.target.replace("\\", "/")
            if target_path.exists():
                preserved = report["preserved-files"]
                assert isinstance(preserved, list)
                preserved.append(relative_target)
            else:
                source_base = source_root / asset.source
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
                created = report["created-files"]
                assert isinstance(created, list)
                created.append(relative_target)
            continue

        source_base = source_root / asset.source
        if not source_base.exists():
            warnings = report["warnings"]
            assert isinstance(warnings, list)
            warnings.append(f"missing source asset: {asset.source}")
            continue

        for source_path, relative_path in _iter_source_files(source_root, asset):
            if asset.recursive:
                target_path = target_root / asset.target / relative_path
                relative_target = str((Path(asset.target) / relative_path).as_posix())
            else:
                target_path = target_root / asset.target
                relative_target = asset.target.replace("\\", "/")

            if source_path.resolve() == target_path.resolve():
                skipped = report["skipped-files"]
                assert isinstance(skipped, list)
                skipped.append({"path": relative_target, "reason": "source-equals-target"})
                continue

            if target_path.exists() and _same_file_contents(source_path, target_path):
                skipped = report["skipped-files"]
                assert isinstance(skipped, list)
                skipped.append({"path": relative_target, "reason": "already-current"})
                continue

            existed = target_path.exists()
            _copy_file(source_path, target_path)
            bucket = "refreshed-files" if existed else "created-files"
            entries = report[bucket]
            assert isinstance(entries, list)
            entries.append(relative_target)

    return report


def render_sync_report(report: dict[str, object]) -> str:
    return json.dumps(report, indent=2, sort_keys=True)
