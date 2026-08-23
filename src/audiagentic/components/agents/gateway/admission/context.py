"""Component-context callable owned by the gateway admission boundary."""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeAlias

ComponentContextReader: TypeAlias = Callable[[Path], dict[str, dict[str, Any]]]


def empty_component_context(_project_root: Path) -> dict[str, dict[str, Any]]:
    """Compatibility reader for unmanaged in-process callers and unit tests."""
    return {}


def baseline_agent_template_context(
    project_root: Path,
    *,
    workspace_name: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Facts global agent prompts may rely on in any filesystem project.

    These remain available when the target has not installed AUDiaGentic
    components.  Descriptor-provided context is layered over this baseline at
    admission, so an enabled component remains the richer authority.
    """
    from audiagentic.components.project.project_api import context as project_context
    from audiagentic.components.source_control.source_control_api import context as source_control_context

    return {
        "project": project_context(project_root, workspace_name=workspace_name),
        "source_control": source_control_context(project_root),
    }


__all__ = ["ComponentContextReader", "baseline_agent_template_context", "empty_component_context"]
