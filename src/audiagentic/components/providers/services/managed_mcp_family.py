"""Descriptor-backed managed-MCP automation family."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.components.providers.contracts.managed_mcp import (
    ManagedMcpMode,
    ManagedMcpRequest,
    ManagedMcpResult,
)
from audiagentic.components.providers.descriptors.registry import get_descriptor
from audiagentic.components.providers.services.managed_mcp_registry import mcp_ownership_registry
from audiagentic.components.providers.services.mcp import (
    get_managed_entry_status,
    sync_managed_provider_mcp_scope,
)
from audiagentic.foundation.mcp import McpServerEntry
from audiagentic.foundation.toolchains.managed_config import REMOTE_CAPABILITY

_SUPPORTED_MODES = frozenset({"apply", "prune", "status"})


def _result(**updates: Any) -> ManagedMcpResult:
    values = {"ok": True, "supported": True, **updates}
    return ManagedMcpResult(**values)


def _desired(request: ManagedMcpRequest) -> dict[str, tuple[str, McpServerEntry]]:
    return {
        item.managed_id: (
            item.name,
            McpServerEntry(
                name=item.name,
                command=item.command or "",
                args=item.args,
                env=dict(item.env),
                url=item.url,
                headers=dict(item.headers),
                transport=item.transport,
            ),
        )
        for item in request.entries
    }


def manage_mcp_entries(
    project_root: Path,
    provider_id: str,
    *,
    mode: ManagedMcpMode,
    request: ManagedMcpRequest,
) -> ManagedMcpResult:
    """Reconcile typed caller-owned MCP entries using descriptor capabilities."""
    descriptor = get_descriptor(provider_id)
    if (
        descriptor is None
        or descriptor.mcp_config is None
        or descriptor.automation_capability("managed-mcp") is None
    ):
        return _result(ok=False, supported=False, provider_id=provider_id, error_code="RES-PREC-001")
    if mode not in _SUPPORTED_MODES:
        return _result(ok=False, provider_id=provider_id, error_code="CON-PREC-002")

    desired = _desired(request)
    if (
        any(entry.is_remote for _, entry in desired.values())
        and REMOTE_CAPABILITY not in descriptor.mcp_config.capabilities
    ):
        return _result(
            ok=False,
            supported=False,
            provider_id=provider_id,
            action_needed="provider MCP config does not support remote entries",
            error_code="CON-PMCP-001",
        )

    internal_scope = f"{provider_id}/{request.ownership_scope}"
    registry = mcp_ownership_registry(project_root)
    before = registry.load().get(internal_scope, {})
    if mode == "status":
        matches = all(
            get_managed_entry_status(provider_id, project_root, name, entry).get("matches")
            for name, entry in desired.values()
        )
        return _result(ok=matches, provider_id=provider_id, managed_ids=tuple(sorted(before)))

    sync = sync_managed_provider_mcp_scope(
        provider_id,
        project_root,
        internal_scope,
        desired if mode == "apply" else {},
        managed_ids=set(desired) if mode == "apply" else None,
    )
    after = registry.load().get(internal_scope, {})
    collisions = sync.get("collisions") or []
    return _result(
        ok=bool(sync.get("ok")),
        provider_id=provider_id,
        changed=bool(sync.get("updated") or sync.get("removed")),
        managed_ids=tuple(sorted(after)),
        removed_ids=tuple(sorted(set(before) - set(after))),
        collision_ids=tuple(sorted({
            str(row.get("managed_id") or row.get("managed-id") or "")
            for row in collisions
        } - {""})),
        auto_refreshed=bool(sync.get("auto_refreshed", False)),
        action_needed=sync.get("action_needed"),
        error_code=None if sync.get("ok") else "CON-PMCP-002",
    )


def adopt_legacy_mcp_ownership(
    project_root: Path,
    *,
    ownership_scope: str,
    managed_ids: frozenset[str],
) -> None:
    """Migrate registry entries from legacy bare provider_id scope to scoped key.

    The old lsp-mcp-projection family used ``provider_id`` as the registry owner
    scope (e.g. ``"claude"``). Managed-mcp uses
    ``f"{provider_id}/{ownership_scope}"`` (e.g. ``"claude/coding-lsp/ag-lsp"``).
    This moves only entries whose managed_id is in *managed_ids* from the legacy
    scope to the new one, dropping emptied legacy scopes. Provider-owned function;
    caller is requester-blind — it passes its scope and managed ids.
    """
    registry = mcp_ownership_registry(project_root)
    data = registry.load()
    if not managed_ids:
        return

    from audiagentic.components.providers.descriptors.registry import all_descriptors

    for provider_id in all_descriptors():
        old_scope_key = provider_id
        new_scope_key = f"{provider_id}/{ownership_scope}"
        old_entries = dict(data.get(old_scope_key, {}))
        if not old_entries:
            continue

        to_migrate = {mid: name for mid, name in old_entries.items() if mid in managed_ids}
        if not to_migrate:
            continue

        # Move entries to new scope
        new_scope_data = data.get(new_scope_key, {})
        new_scope_data.update(to_migrate)
        data[new_scope_key] = new_scope_data
        for mid in to_migrate:
            old_entries.pop(mid, None)

        # Clean up empty old scope if only migrated entries were there
        if not old_entries:
            data.pop(old_scope_key, None)

    registry.save(data)


__all__ = ["adopt_legacy_mcp_ownership", "manage_mcp_entries"]
