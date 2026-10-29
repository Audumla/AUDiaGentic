"""Doctor checks owned by the project component (read-only)."""
from __future__ import annotations

from typing import Any

from audiagentic.foundation.config.settings import discover_project_root
from audiagentic.foundation.lifecycle.doctor import FAIL, OK, WARN, CheckResult

from .project_api import project_identity


def check_identity(context: Any) -> list[CheckResult]:
    root = discover_project_root(context.project)
    if root is None:
        return [CheckResult("project.identity", OK, "no project here (outside a git checkout)")]
    name, source = project_identity(root)
    if source in {"main-checkout", "folder"}:
        return [CheckResult("project.identity", WARN, f"project name {name!r} comes from a directory name ({source})",
                            "Set project-name in .audiagentic/config/project.yaml or add a git origin remote, "
                            "so every clone resolves the same project")]
    return [CheckResult("project.identity", OK, f"project {name!r} ({source})")]


def check_mcp_onboarding(context: Any) -> list[CheckResult]:
    root = discover_project_root(context.project)
    if root is None:
        return [CheckResult("mcp.onboarding", OK, "no project here")]
    from .onboarding.service import status

    state = status(root)
    if state.get("has_unresolved_operation") is False:
        return [CheckResult("mcp.onboarding", OK, "no unfinished MCP installation")]
    mcp_id = state.get("mcp_id", "the MCP")
    return [CheckResult("mcp.onboarding", FAIL, f"MCP installation for {mcp_id} is {state.get('phase', 'incomplete')}",
                        "Repeat the same 'audiagentic mcp install' command to resume it")]
