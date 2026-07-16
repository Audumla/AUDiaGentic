"""Descriptor-backed LSP-MCP projection automation family (Pattern B)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.components.providers.contracts.lsp_mcp_projection import (
    LspMcpProjectionEntry,
    LspMcpProjectionMode,
    LspMcpProjectionRequest,
    LspMcpProjectionResult,
)
from audiagentic.components.providers.descriptors.registry import get_descriptor
from audiagentic.components.providers.services.mcp import (
    sync_managed_provider_mcp_subset,
)
from audiagentic.foundation.mcp import McpServerEntry

FAMILY_ID = "lsp-mcp-projection"

_SUPPORTED_MODES = frozenset({"apply", "prune", "status"})


def _result(**updates: Any) -> LspMcpProjectionResult:
    values = {"ok": True, **updates}
    return LspMcpProjectionResult(**values)


def _to_mcp_entry(entry: LspMcpProjectionEntry) -> McpServerEntry:
    return McpServerEntry(
        name=entry.name,
        command=entry.command or "",
        args=entry.args,
        env=dict(entry.env),
        url=entry.url,
        headers=dict(entry.headers),
        transport=entry.transport,
    )


def manage_lsp_mcp_projection(
    project_root: Path,
    provider_id: str,
    *,
    mode: LspMcpProjectionMode,
    request: LspMcpProjectionRequest,
) -> LspMcpProjectionResult:
    """Reconcile typed LSP-MCP entries using descriptor capabilities."""
    descriptor = get_descriptor(provider_id)
    if (
        descriptor is None
        or descriptor.mcp_config is None
        or not descriptor.receive_lsp_mcp
        or descriptor.automation_capability(FAMILY_ID) is None
    ):
        return _result(ok=False, provider_id=provider_id, error_code="RES-PREC-001")
    if mode not in _SUPPORTED_MODES:
        return _result(ok=False, provider_id=provider_id, error_code="CON-PREC-002")

    desired = {
        entry.managed_id: (entry.name, _to_mcp_entry(entry))
        for entry in request.entries
    }

    if mode == "status":
        try:
            spec = descriptor.mcp_config
            from audiagentic.foundation.toolchains.managed_config import (
                resolve_managed_config_path,
            )
            config_path = resolve_managed_config_path(spec, project_root)
            current = spec.reader(config_path)
            synced = [
                entry.managed_id
                for entry in request.entries
                if entry.managed_id in current
            ]
            return _result(
                provider_id=provider_id,
                synced=tuple(sorted(synced)),
                skipped=tuple(sorted(set(entry.managed_id for entry in request.entries) - set(synced))),
            )
        except Exception:
            return _result(ok=False, provider_id=provider_id, error_code="CON-PLMC-001")

    if mode == "apply":
        try:
            sync = sync_managed_provider_mcp_subset(
                provider_id=provider_id,
                project_root=project_root,
                desired_entries=desired,
                managed_ids=set(request.managed_ids),
            )
            return _result(
                ok=bool(sync.get("ok")),
                provider_id=provider_id,
                synced=tuple(sorted(desired)),
                error_code=None if sync.get("ok") else "CON-PLMC-002",
                action_needed=sync.get("action_needed"),
            )
        except Exception:
            return _result(ok=False, provider_id=provider_id, error_code="CON-PLMC-002")

    # mode == "prune"
    try:
        sync = sync_managed_provider_mcp_subset(
            provider_id=provider_id,
            project_root=project_root,
            desired_entries={},
            managed_ids=set(request.managed_ids),
        )
        return _result(
            ok=bool(sync.get("ok")),
            provider_id=provider_id,
            pruned=tuple(sorted(request.managed_ids)),
            error_code=None if sync.get("ok") else "CON-PLMC-003",
        )
    except Exception:
        return _result(ok=False, provider_id=provider_id, error_code="CON-PLMC-003")


def manage_lsp_mcp_projection_all(
    project_root: Path,
    *,
    mode: LspMcpProjectionMode,
    request: LspMcpProjectionRequest,
) -> list[LspMcpProjectionResult]:
    """Project LSP-MCP entries to all eligible providers.

    Only providers with mcp_config and receive_lsp_mcp=True are included.
    Enabled providers get the desired set; disabled providers get an empty set
    so managed entries are pruned.
    """
    from audiagentic.components.providers.descriptors.registry import all_descriptors
    from audiagentic.components.providers.services.feature_resolution import (
        enabled_provider_ids,
    )

    enabled = enabled_provider_ids(project_root)
    results: list[LspMcpProjectionResult] = []
    for descriptor in sorted(all_descriptors().values(), key=lambda d: d.provider_id):
        if descriptor.mcp_config is None or not descriptor.receive_lsp_mcp:
            continue
        pid = descriptor.provider_id
        if mode == "apply":
            # Disabled providers get empty desired set (prune managed entries)
            actual_request = request if pid in enabled else LspMcpProjectionRequest(
                managed_ids=request.managed_ids, entries=()
            )
        elif mode == "status":
            # Skip status for disabled providers
            if pid not in enabled:
                continue
            actual_request = request
        else:
            # prune mode
            actual_request = request

        result = manage_lsp_mcp_projection(
            project_root, pid, mode=mode, request=actual_request,
        )
        results.append(result)
    return results


__all__ = ["manage_lsp_mcp_projection", "manage_lsp_mcp_projection_all"]
