"""Internal source-control service API shared by MCP wrappers and in-process callers."""
from __future__ import annotations

from typing import Any

from audiagentic.components.optional.source_control.source_control_bootstrap import (
    SOURCE_CONTROL_DEPENDENCY_IDS,
    detect_availability,
)
from audiagentic.foundation.dependencies import (
    detect_missing,
    load_component_probes,
    load_component_workflow,
)
from audiagentic.foundation.workflow.invocation.steps import SequenceStep

_PROBES = load_component_probes("source-control")


def get_source_control_status() -> dict[str, Any]:
    missing = detect_missing(_PROBES, SOURCE_CONTROL_DEPENDENCY_IDS)
    return {**detect_availability(), "missing-dependencies": missing}


async def install_dependencies(names: list[str], *, ctx, run_with_output) -> dict[str, Any]:
    workflow = load_component_workflow("source-control", action="install")
    filtered = workflow.steps if not names else tuple(
        s for s in workflow.steps if s.id in names
    )
    seq = SequenceStep(id="install", steps=filtered, fail_fast=False)
    return await run_with_output(
        ctx=ctx,
        logger="source-control.dependencies.install",
        heartbeat_message="Dependency install still running...",
        work=lambda _: seq.run({}),
    )


async def uninstall_dependencies(names: list[str], *, ctx, run_with_output) -> dict[str, Any]:
    workflow = load_component_workflow("source-control", action="uninstall")
    filtered = workflow.steps if not names else tuple(
        s for s in workflow.steps if s.id in names
    )
    seq = SequenceStep(id="uninstall", steps=filtered, fail_fast=False)
    return await run_with_output(
        ctx=ctx,
        logger="source-control.dependencies.uninstall",
        heartbeat_message="Dependency uninstall still running...",
        work=lambda _: seq.run({}),
    )
