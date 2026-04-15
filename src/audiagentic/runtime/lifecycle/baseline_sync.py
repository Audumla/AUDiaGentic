"""Managed install-baseline inventory and synchronization helpers.

See spec 50 for the required-managed/create-if-missing/generated-managed/runtime-only
contract that this inventory enforces.
"""
from __future__ import annotations

import json
import shutil
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_DOC_DIRS: tuple[str, ...] = ("specifications", "implementation", "releases", "decisions")

MODE_REQUIRED_MANAGED = "required-managed"
MODE_CREATE_IF_MISSING = "create-if-missing"
MODE_GENERATED_MANAGED = "generated-managed"
MODE_RUNTIME_ONLY = "runtime-only"


@dataclass(frozen=True)
class BaselineAsset:
    source: str
    target: str
    mode: str
    recursive: bool = False


BASELINE_ASSETS: tuple[BaselineAsset, ...] = (
    BaselineAsset(".audiagentic/project.yaml", ".audiagentic/project.yaml", MODE_CREATE_IF_MISSING),
    BaselineAsset(".audiagentic/components.yaml", ".audiagentic/components.yaml", MODE_CREATE_IF_MISSING),
    BaselineAsset(".audiagentic/providers.yaml", ".audiagentic/providers.yaml", MODE_CREATE_IF_MISSING),
    BaselineAsset(".audiagentic/prompt-syntax.yaml", ".audiagentic/prompt-syntax.yaml", MODE_CREATE_IF_MISSING),
    BaselineAsset(".audiagentic/prompts", ".audiagentic/prompts", MODE_REQUIRED_MANAGED, recursive=True),
    BaselineAsset("AGENTS.md", "AGENTS.md", MODE_REQUIRED_MANAGED),
    BaselineAsset("CLAUDE.md", "CLAUDE.md", MODE_REQUIRED_MANAGED),
    BaselineAsset("GEMINI.md", "GEMINI.md", MODE_REQUIRED_MANAGED),
    BaselineAsset(".gemini", ".gemini", MODE_REQUIRED_MANAGED, recursive=True),
    BaselineAsset(".clinerules", ".clinerules", MODE_REQUIRED_MANAGED, recursive=True),
    BaselineAsset(".claude", ".claude", MODE_REQUIRED_MANAGED, recursive=True),
    BaselineAsset(".agents/skills", ".agents/skills", MODE_REQUIRED_MANAGED, recursive=True),
    BaselineAsset(".opencode", ".opencode", MODE_REQUIRED_MANAGED, recursive=True),
    BaselineAsset(
        ".github/workflows/release-please.audiagentic.yml",
        ".github/workflows/release-please.audiagentic.yml",
        MODE_REQUIRED_MANAGED,
    ),
    BaselineAsset("docs/releases", "docs/releases", MODE_GENERATED_MANAGED, recursive=True),
    BaselineAsset(".audiagentic/runtime", ".audiagentic/runtime", MODE_RUNTIME_ONLY, recursive=True),
    BaselineAsset(
        ".audiagentic/planning/config",
        ".audiagentic/planning/config",
        MODE_CREATE_IF_MISSING,
        recursive=True,
    ),
)


def list_baseline_assets() -> list[dict[str, object]]:
    return [
        {
            "source": asset.source,
            "target": asset.target,
            "mode": asset.mode,
            "recursive": asset.recursive,
        }
        for asset in BASELINE_ASSETS
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


def sync_managed_baseline(
    target_root: Path,
    *,
    source_root: Path | None = None,
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

    for asset in BASELINE_ASSETS:
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

            if asset.mode == MODE_CREATE_IF_MISSING and target_path.exists():
                preserved = report["preserved-files"]
                assert isinstance(preserved, list)
                preserved.append(relative_target)
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
