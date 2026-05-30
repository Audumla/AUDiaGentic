"""Internal source-control service API shared by MCP wrappers and in-process callers."""
from __future__ import annotations

from typing import Any

from audiagentic.components.optional.source_control.source_control_bootstrap import (
    SOURCE_CONTROL_DEPENDENCY_IDS,
    detect_availability,
)
from audiagentic.foundation.dependencies import (
    SYSTEM_DEPENDENCIES,
    detect_missing,
    install_system_dependencies,
    uninstall_system_dependencies,
)


def get_source_control_status() -> dict[str, Any]:
    missing = detect_missing(SYSTEM_DEPENDENCIES, SOURCE_CONTROL_DEPENDENCY_IDS)
    return {**detect_availability(), "missing-dependencies": missing}


async def install_dependencies(names: list[str], *, ctx, run_with_output) -> dict[str, Any]:
    return await run_with_output(
        ctx=ctx,
        logger="source-control.dependencies.install",
        heartbeat_message="Dependency install still running...",
        work=lambda output: install_system_dependencies(names, on_progress=output),
    )


async def uninstall_dependencies(names: list[str], *, ctx, run_with_output) -> dict[str, Any]:
    return await run_with_output(
        ctx=ctx,
        logger="source-control.dependencies.uninstall",
        heartbeat_message="Dependency uninstall still running...",
        work=lambda output: uninstall_system_dependencies(names, on_progress=output),
    )
