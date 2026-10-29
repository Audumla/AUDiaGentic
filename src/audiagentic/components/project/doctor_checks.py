"""Doctor checks owned by the project component (read-only)."""
from __future__ import annotations

from typing import Any

from audiagentic.foundation.config.settings import discover_project_root
from audiagentic.foundation.lifecycle.doctor import FAIL, OK, WARN, CheckResult

from .project_api import git_remote_ids, project_id

_DECLARE = (
    "Declare project.id in the tracked .audiagentic/settings.yaml, so every clone resolves the same "
    "project (providers such as gpt-auto use it as the project name)"
)


def check_identity(context: Any) -> list[CheckResult]:
    root = discover_project_root(context.project)
    if root is None:
        return [CheckResult("project.identity", OK, "no project here (outside a git checkout)")]
    identity, source = project_id(root)
    if source in {"settings", "legacy"}:
        return [CheckResult("project.identity", OK, f"project id {identity!r} ({source})")]
    remote_ids = git_remote_ids(root)
    if len(set(remote_ids.values())) > 1:
        names = ", ".join(f"{remote}={repo_id}" for remote, repo_id in sorted(remote_ids.items()))
        return [CheckResult("project.identity", WARN, f"git remotes name different repositories ({names})", _DECLARE)]
    if source in {"main-checkout", "folder"}:
        return [CheckResult("project.identity", WARN, f"project id {identity!r} comes from a directory name ({source})",
                            f"{_DECLARE}, or add a git origin remote")]
    return [CheckResult("project.identity", OK, f"project id {identity!r} ({source})")]


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
