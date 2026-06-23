"""Internal source-control service API shared by MCP wrappers and in-process callers."""
from __future__ import annotations

import asyncio
from typing import Any

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
from audiagentic.foundation.workflow.invocation.steps import SequenceStep

_PROBES = load_dependency_probes("source-control")

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


async def install_dependencies(names: list[str]) -> dict[str, Any]:
    workflow = load_dependency_workflow("source-control", action="install")
    filtered = workflow.steps if not names else tuple(
        s for s in workflow.steps if s.id in names
    )
    seq = SequenceStep(id="install", steps=filtered, fail_fast=False)
    result = await asyncio.to_thread(seq.run, {})
    return {"status": result.status, "reason": result.reason or "", "outputs": result.outputs}


async def uninstall_dependencies(names: list[str]) -> dict[str, Any]:
    workflow = load_dependency_workflow("source-control", action="uninstall")
    filtered = workflow.steps if not names else tuple(
        s for s in workflow.steps if s.id in names
    )
    seq = SequenceStep(id="uninstall", steps=filtered, fail_fast=False)
    result = await asyncio.to_thread(seq.run, {})
    return {"status": result.status, "reason": result.reason or "", "outputs": result.outputs}
