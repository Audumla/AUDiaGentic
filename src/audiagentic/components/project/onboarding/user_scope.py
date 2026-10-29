"""User-scope MCP registration for ``audiagentic setup`` (CFG08).

Registers every worktree-scoped server a component exposes to native clients
at the user scope of each harness the user names, through the providers API.
Such a server is bound to no project (each call selects its worktree), so one
registration serves every directory. Only explicitly named harnesses are
touched, and nothing here reads or writes a project.
"""

from __future__ import annotations

from audiagentic.components.providers import providers_api
from audiagentic.foundation.components.loader import register_all_components
from audiagentic.foundation.components.registry import all_descriptors
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.mcp.component_builder import user_entry_from_mcp_declaration

OWNERSHIP_SCOPE = "component-mcp"


def _error(message: str, **details) -> AudiaGenticError:
    return AudiaGenticError(code="VAL-MCPUSR-001", kind="project", message=message, details=details)


def user_scope_request() -> providers_api.ManagedMcpRequest:
    """Entries for every worktree-scoped, provider-propagated MCP server."""
    register_all_components()
    entries = []
    for descriptor in all_descriptors().values():
        for decl in descriptor.mcp_servers:
            if not decl.worktree_scoped or "providers" not in decl.propagate:
                continue
            entry = user_entry_from_mcp_declaration(decl)
            entries.append(providers_api.ManagedMcpEntry(
                managed_id=decl.managed_id or decl.name, name=decl.name,
                command=entry.command, args=entry.args,
            ))
    return providers_api.ManagedMcpRequest(
        OWNERSHIP_SCOPE, None, tuple(sorted(entries, key=lambda item: item.managed_id))
    )


def user_scope_targets() -> list[str]:
    return [t.provider_id for t in providers_api.list_harness_mcp_targets() if t.supported and t.user_scoped]


def setup_user_mcp(harness_ids: list[str], *, dry_run: bool = False) -> list[dict]:
    """Register at each named harness's user scope; a dry run only reports state."""
    unknown = sorted(set(harness_ids) - set(user_scope_targets()))
    if unknown:
        raise _error("These harnesses have no user-scope MCP registration", harness_ids=unknown,
                     supported=user_scope_targets())
    request = user_scope_request()
    if dry_run:
        return [providers_api.user_mcp_status(pid, request=request) for pid in harness_ids]
    return [providers_api.reconcile_user_mcp(pid, request=request) for pid in harness_ids]


def user_mcp_states() -> list[dict]:
    """Read-only state at every user-scope target (for doctor)."""
    request = user_scope_request()
    return [providers_api.user_mcp_status(pid, request=request) for pid in user_scope_targets()]
