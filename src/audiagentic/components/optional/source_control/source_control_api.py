"""Internal source-control service API shared by MCP wrappers and in-process callers."""
from __future__ import annotations

from typing import Any

from audiagentic.components.optional.source_control.source_control_bootstrap import (
    SOURCE_CONTROL_DEPENDENCY_IDS,
    detect_availability,
)
from audiagentic.foundation.dependencies import (
    detect_missing,
    load_component_dependencies,
)
from audiagentic.foundation.dependencies import (
    install_dependencies as _install,
)
from audiagentic.foundation.dependencies import (
    uninstall_dependencies as _uninstall,
)

_DEPS = load_component_dependencies("source-control")


def get_source_control_status() -> dict[str, Any]:
    missing = detect_missing(_DEPS, SOURCE_CONTROL_DEPENDENCY_IDS)
    return {**detect_availability(), "missing-dependencies": missing}


async def install_dependencies(names: list[str], *, ctx, run_with_output) -> dict[str, Any]:
    return await run_with_output(
        ctx=ctx,
        logger="source-control.dependencies.install",
        heartbeat_message="Dependency install still running...",
        work=lambda output: _install(_DEPS, names, on_progress=output),
    )


async def uninstall_dependencies(names: list[str], *, ctx, run_with_output) -> dict[str, Any]:
    return await run_with_output(
        ctx=ctx,
        logger="source-control.dependencies.uninstall",
        heartbeat_message="Dependency uninstall still running...",
        work=lambda output: _uninstall(_DEPS, names, on_progress=output),
    )
