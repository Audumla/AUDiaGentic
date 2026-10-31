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
    if source == "settings":
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


def check_user_mcp(context: Any) -> list[CheckResult]:
    """User-scope MCP registrations made by setup: configured, or the fix to restore them."""
    from .onboarding.user_scope import user_mcp_states

    results = []
    for state in user_mcp_states():
        check = f"mcp.user.{state['provider_id']}"
        if not state["registered"]:
            results.append(CheckResult(check, OK, "no user-scope MCP registration (optional)"))
            continue
        problems = [f"{entry['name']} {entry['state']}" for entry in state["entries"] if entry["state"] != "configured"]
        if not problems:
            results.append(CheckResult(check, OK, f"worktree-scoped MCP servers configured in {state['target']}"))
        else:
            results.append(CheckResult(check, WARN, f"user-scope MCP: {', '.join(problems)}",
                                       f"audiagentic setup harness {state['provider_id']}"))
    return results


def check_primary_checkout(context: Any) -> list[CheckResult]:
    """The main worktree is a clean base: on the remote default branch, not behind or diverged."""
    from audiagentic.foundation.paths.project import discover_checkout_root

    repo = discover_checkout_root(context.project)
    if repo is None:
        return [CheckResult("worktrees.primary", OK, "no git repository here")]
    from .worktrees.service import primary_checkout_problems

    try:
        problems = primary_checkout_problems(repo)
    except Exception as error:  # noqa: BLE001 - doctor reports, it does not raise
        return [CheckResult("worktrees.primary", WARN, f"cannot inspect the main worktree: {type(error).__name__}")]
    if not problems:
        return [CheckResult("worktrees.primary", OK, "the main worktree is a clean base")]
    return [CheckResult(
        "worktrees.primary", WARN, "; ".join(problems),
        "Archive any local-only history on a local archive/<purpose>-<date> branch, then fast-forward or "
        "reset the main worktree to the remote default branch; do not develop in it",
    )]
