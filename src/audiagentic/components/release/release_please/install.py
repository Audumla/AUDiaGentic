from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from audiagentic.foundation.contracts.errors import make_error
from audiagentic.foundation.io import atomic_write_text
from audiagentic.foundation.lifecycle.components import DEFAULT_VERSION
from audiagentic.foundation.toolchains.artifact_registry import ArtifactRegistry

from . import utils

logger = logging.getLogger(__name__)

SUPPORTED_RELEASE_TYPES = ["python", "node", "java", "go", "rust", "simple"]
_RELEASE_RECIPE = "release/release-please"

TEMPLATE_PLACEHOLDERS = {
    "release-please-config.json": ["__RELEASE_TYPE__"],
    "release.yml": ["__BRANCH__", "__PYTHON_VERSION__"],
    "baseline.yml": ["__BRANCH__", "__PYTHON_VERSION__"],
}


def _validate_render(template_name: str, text: str, subs: dict[str, str]) -> None:
    expected = set(TEMPLATE_PLACEHOLDERS.get(template_name, []))
    for placeholder in expected:
        if placeholder in text:
            raise make_error(
                prefix="VAL", component="release", number=2,
                kind="release",
                message=f"unreplaced placeholder in {template_name}",
                details={"placeholder": placeholder},
            )


def _registry(project_root: Path) -> ArtifactRegistry:
    return ArtifactRegistry(project_root)


def install(
    project_root: Path,
    release_type: str = "python",
    branch: str = "main",
    python_version: str = "3.13",
    initial_version: str = DEFAULT_VERSION,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    if release_type not in SUPPORTED_RELEASE_TYPES:
        raise make_error(
            prefix="VAL", component="release", number=1,
            kind="release",
            message="unsupported release type",
            details={
                "release-type": release_type,
                "supported-release-types": list(SUPPORTED_RELEASE_TYPES),
            },
        )

    subs = {
        "__RELEASE_TYPE__": release_type,
        "__BRANCH__": branch,
        "__PYTHON_VERSION__": python_version,
    }
    rendered_config = utils.render("release-please-config.json", subs)
    _validate_render("release-please-config.json", rendered_config, subs)
    rendered_workflow = utils.render("release.yml", subs)
    _validate_render("release.yml", rendered_workflow, subs)

    files = {
        project_root / "release-please-config.json": rendered_config,
        project_root / ".release-please-manifest.json": json.dumps({".": initial_version}, indent=2) + "\n",
        project_root / ".github" / "workflows" / "release.yml": rendered_workflow,
    }

    created, adopted, collisions = [], [], []
    dry_run_changes: list[dict[str, Any]] = []

    for path, content in files.items():
        rel = str(path.relative_to(project_root)) if path.is_relative_to(project_root) else str(path)

        if not path.exists():
            # Absent file → create whole-owned
            if dry_run:
                dry_run_changes.append({
                    "path": rel,
                    "action": "create",
                    "bytes_new": len(content.encode("utf-8")),
                })
            else:
                atomic_write_text(path, content)
            created.append(rel)
        else:
            existing = path.read_text(encoding="utf-8")
            if existing == content:
                # Byte-for-byte match → adopt as owned
                adopted.append(rel)
            else:
                # Content differs → collision, never overwrite
                collisions.append(rel)

    result: dict[str, Any] = {
        "created": created,
        "adopted": adopted,
        "collisions": collisions,
        "skipped": [],  # legacy key retained for compatibility; now empty (replaced by collisions/adopted)
    }

    if collisions:
        logger.warning(
            "Release file collision — existing files have divergent content and were not overwritten: %s",
            collisions,
        )

    if dry_run:
        result["dry_run_changes"] = dry_run_changes
    else:
        reg = _registry(project_root)
        all_owned = created + adopted
        if all_owned:
            reg.register(_RELEASE_RECIPE, files=all_owned)

    return result
