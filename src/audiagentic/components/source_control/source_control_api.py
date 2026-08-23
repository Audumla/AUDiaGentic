"""Internal source-control service API shared by MCP wrappers and in-process callers."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from dulwich.repo import Repo

from audiagentic.components.source_control.source_control_bootstrap import (
    SOURCE_CONTROL_DEPENDENCY_IDS,
    detect_availability,
)
from audiagentic.foundation.components.dependencies import (
    detect_missing,
    load_dependency_probes,
    load_dependency_workflow,
    validate_dependency_versions,
)
from audiagentic.foundation.components.loader import component_yaml_path
from audiagentic.foundation.io import load_yaml_file
from audiagentic.foundation.steps import SequenceStep

_PROBES = load_dependency_probes("source-control")


def _empty_context(project_root: Path) -> dict[str, Any]:
    return {
        "repository": None,
        "repository_name": project_root.name,
        "root": None,
        "branch": None,
        "commit": None,
        "commit_short": None,
        "detached": False,
    }


def _decode_ref(value: bytes | None) -> str | None:
    if not value:
        return None
    try:
        decoded = value.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return decoded or None


def _origin_url(repository: Repo) -> str | None:
    """Read the canonical origin URL without invoking git.exe."""
    try:
        value = repository.get_config().get((b"remote", b"origin"), b"url")
    except Exception:
        return None
    return _decode_ref(value) if isinstance(value, bytes) else None


def context(project_root: Path) -> dict[str, Any]:
    """Return bounded, read-only local Git facts for prompt templates."""
    try:
        repository = Repo.discover(str(project_root))
    except Exception:
        # Source-control facts are optional prompt context.  A malformed or
        # unavailable repository must never reject gateway admission.
        return _empty_context(project_root)

    try:
        root = Path(repository.get_worktree().path).resolve()
        try:
            commit = _decode_ref(repository.head())
            raw_head = repository.refs.read_ref(b"HEAD")
        except Exception:
            # An unborn repository still has a useful working-tree identity,
            # but no branch or commit to contribute.
            commit = None
            raw_head = None

        branch_prefix = b"ref: refs/heads/"
        branch = (
            _decode_ref(raw_head[len(branch_prefix):])
            if raw_head and raw_head.startswith(branch_prefix)
            else None
        )
        return {
            "repository": _origin_url(repository),
            "repository_name": root.name,
            "root": str(root),
            "branch": branch,
            "commit": commit,
            "commit_short": commit[:12] if commit else None,
            "detached": bool(commit and not branch),
        }
    except Exception:
        return _empty_context(project_root)
    finally:
        repository.close()

def _load_dep_cfgs() -> dict[str, Any]:
    cfg = load_yaml_file(component_yaml_path("source-control"))
    return cfg.get("dependencies") or {}

def get_source_control_status() -> dict[str, Any]:
    missing = detect_missing(_PROBES, SOURCE_CONTROL_DEPENDENCY_IDS)
    version_warnings = validate_dependency_versions(_load_dep_cfgs())
    result = {**detect_availability(), "missing-dependencies": missing}
    if version_warnings:
        result["version-warnings"] = version_warnings
    return result


def _run_workflow(action: str, names: list[str]) -> dict[str, Any]:
    workflow = load_dependency_workflow("source-control", action=action)
    filtered = workflow.steps if not names else tuple(
        s for s in workflow.steps if s.id in names
    )
    seq = SequenceStep(id=action, steps=filtered, fail_fast=False)
    result = asyncio.get_event_loop().run_until_complete(asyncio.to_thread(seq.run, {}))
    return {"status": result.status, "reason": result.reason or "", "outputs": result.outputs}


async def install_dependencies(names: list[str]) -> dict[str, Any]:
    return _run_workflow("install", names)


async def uninstall_dependencies(names: list[str]) -> dict[str, Any]:
    return _run_workflow("uninstall", names)
