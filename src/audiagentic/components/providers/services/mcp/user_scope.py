"""Harness user-scope MCP registration (CFG08), owned by providers.

A harness may declare ``user_scope`` under its ``mcp`` mechanism: the
per-user MCP registration that applies in every directory. Only entries for
worktree-scoped servers belong there (the caller selects the worktree on each
call), and the requester supplies them already built.

Ownership reuses the shared fragment engine: AUDiaGentic changes only names
it registered itself, recorded in the user state directory per target file
(Claude keeps one user config per ``CLAUDE_CONFIG_DIR``). A name that exists
but was not registered here is foreign and reported, never overwritten.
"""

from __future__ import annotations

from pathlib import Path

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.paths.home import user_state_dir
from audiagentic.foundation.system.advisory_lock import AdvisoryLock
from audiagentic.foundation.toolchains.config.fragments import FragmentStore, reconcile_fragments
from audiagentic.foundation.toolchains.config.managed_config import (
    ManagedConfigSpec,
    ManagedFragmentRegistry,
    resolve_managed_config_path,
)

from ...contracts.managed_mcp import ManagedMcpRequest
from ...descriptors.registry import get_descriptor
from ..capabilities.managed_mcp_family import _desired

CONFIGURED, MISSING, DRIFTED, FOREIGN = "configured", "missing", "drifted", "foreign"


def _error(message: str, **details) -> AudiaGenticError:
    return AudiaGenticError(code="CON-MCPUSR-001", kind="providers", message=message, details=details)


def _spec(provider_id: str) -> ManagedConfigSpec:
    descriptor = get_descriptor(provider_id)
    spec = descriptor.mcp_config.user_scope if descriptor and descriptor.mcp_config else None
    if spec is None:
        raise _error("This harness declares no user-scope MCP registration", provider_id=provider_id)
    return spec


def _registry() -> ManagedFragmentRegistry:
    root = user_state_dir()
    return ManagedFragmentRegistry(root, "user-mcp-servers.json",
                                   storage_path=root / "providers" / "user-mcp-servers.json")


def _scope(provider_id: str, request: ManagedMcpRequest, path: Path) -> str:
    return f"{provider_id}/{request.ownership_scope}:{path}"


def user_mcp_status(provider_id: str, request: ManagedMcpRequest) -> dict:
    """Read-only: each requested entry is configured, missing, drifted or foreign.

    ``registered`` says whether this owner has registered anything at the
    target, so a harness the user never asked for is not reported as missing.
    """
    spec = _spec(provider_id)
    path = resolve_managed_config_path(spec, None)
    owned = _registry().load().get(_scope(provider_id, request, path), {})
    current = spec.reader(path)
    entries = []
    for managed_id, (name, payload) in _desired(request).items():
        if name not in current:
            state = MISSING
        elif owned.get(managed_id) != name:
            state = FOREIGN
        else:
            state = CONFIGURED if current[name] == payload else DRIFTED
        entries.append({"managed_id": managed_id, "name": name, "state": state})
    return {"provider_id": provider_id, "target": str(path), "registered": bool(owned), "entries": entries}


def reconcile_user_mcp(provider_id: str, request: ManagedMcpRequest) -> dict:
    """Make the harness's user scope hold exactly the requested entries this owner manages."""
    spec = _spec(provider_id)
    path = resolve_managed_config_path(spec, None)
    registry = _registry()
    registry.path.parent.mkdir(parents=True, exist_ok=True)
    with AdvisoryLock(registry.path.with_suffix(".lock")):
        result = reconcile_fragments(
            FragmentStore(read=spec.reader, write=spec.writer, remove=spec.remover),
            path,
            _scope(provider_id, request, path),
            _desired(request),
            registry_load=registry.load,
            registry_save=registry.save,
        )
    return {
        "provider_id": provider_id,
        "target": str(path),
        "ok": result.ok,
        "changed": result.changed,
        "updated": list(result.updated),
        "removed": list(result.removed),
        "collisions": list(result.collisions),
    }
