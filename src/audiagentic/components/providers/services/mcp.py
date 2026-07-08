"""Provider MCP config management — add, remove, list, reload per-provider MCP server entries.

Also provides generic MCP config helpers that wrap foundation ConfigPatcher,
scoped to provider-specific config paths.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.mcp import McpServerEntry
from audiagentic.foundation.toolchains.config_patcher import ConfigPatcher
from audiagentic.foundation.toolchains.fragments import FragmentStore, reconcile_fragments

from ..descriptors.base import McpConfigSpec, ProviderDescriptor
from ..descriptors.registry import get_descriptor
from .managed_mcp_registry import load_managed_mcp_registry, save_managed_mcp_registry


def _descriptor(provider_id: str) -> ProviderDescriptor:
    descriptor = get_descriptor(provider_id)
    if descriptor is None:
        raise AudiaGenticError(
            code="VAL-MCP-001",
            kind="providers",
            message="unknown provider",
            details={"provider-id": provider_id},
        )
    return descriptor


def _resolve_mcp_path(spec: McpConfigSpec, project_root: Path) -> Path:
    if callable(spec.config_path):
        return spec.config_path(project_root)
    p = Path(spec.config_path).expanduser()
    if p.is_absolute():
        return p
    return project_root / p


def add_provider_mcp_server(
    provider_id: str,
    name: str,
    command: str,
    project_root: Path,
    *,
    args: tuple[str, ...] = (),
    env: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Add or update a single MCP server entry in a provider's config, then reload."""
    descriptor = _descriptor(provider_id)
    spec = descriptor.mcp_config
    if spec is None:
        return {"provider_id": provider_id, "ok": False, "error": "no mcp_config defined for this provider"}

    config_path = _resolve_mcp_path(spec, project_root)
    entry = McpServerEntry(name=name, command=command, args=tuple(args), env=dict(env or {}))
    spec.writer(config_path, {name: entry})
    result: dict[str, Any] = {
        "provider_id": provider_id,
        "ok": True,
        "config_path": str(config_path),
        "server_name": name,
    }
    result.update(reload_provider_mcp(provider_id, project_root))
    return result


def remove_provider_mcp_server(
    provider_id: str,
    server_name: str,
    project_root: Path,
) -> dict[str, Any]:
    """Remove a single MCP server entry from a provider's config, then reload."""
    descriptor = _descriptor(provider_id)
    spec = descriptor.mcp_config
    if spec is None:
        return {"provider_id": provider_id, "ok": False, "error": "no mcp_config defined for this provider"}

    config_path = _resolve_mcp_path(spec, project_root)
    removed = spec.remover(config_path, server_name)
    result: dict[str, Any] = {
        "provider_id": provider_id,
        "ok": True,
        "config_path": str(config_path),
        "server_name": server_name,
        "removed": removed,
    }
    if removed:
        result.update(reload_provider_mcp(provider_id, project_root))
    return result


def list_provider_mcp_servers(
    provider_id: str,
    project_root: Path,
) -> dict[str, Any]:
    """Return current MCP server entries from a provider's config."""
    descriptor = _descriptor(provider_id)
    spec = descriptor.mcp_config
    if spec is None:
        return {"provider_id": provider_id, "ok": True, "servers": [], "skipped": "no mcp_config defined"}

    config_path = _resolve_mcp_path(spec, project_root)
    current = spec.reader(config_path)
    return {
        "provider_id": provider_id,
        "ok": True,
        "config_path": str(config_path),
        "format": spec.format,
        "refresh_mode": spec.refresh_mode,
        "config_exists": config_path.exists(),
        "servers": [
            {"name": e.name, "command": e.command, "args": list(e.args)}
            for e in current.values()
        ],
    }


def reload_provider_mcp(
    provider_id: str,
    project_root: Path,
) -> dict[str, Any]:
    """Signal or reload a provider after its MCP config has changed.

    file-watch providers auto-reload on file change — nothing extra needed.
    restart-required providers call reload_fn if defined, otherwise inform only.
    """
    descriptor = _descriptor(provider_id)
    spec = descriptor.mcp_config
    if spec is None:
        return {"provider_id": provider_id, "ok": False, "error": "no mcp_config defined for this provider"}

    if spec.refresh_mode == "file-watch":
        return {
            "provider_id": provider_id,
            "ok": True,
            "auto_refreshed": True,
            "method": "file-watch",
        }

    if spec.reload_fn is not None:
        try:
            fn_result = spec.reload_fn(project_root)
        except Exception as exc:  # noqa: BLE001
            return {
                "provider_id": provider_id,
                "ok": False,
                "method": "reload-fn",
                "error": str(exc),
            }
        return {
            "provider_id": provider_id,
            "ok": True,
            "auto_refreshed": True,
            "method": "reload-fn",
            **fn_result,
        }

    return {
        "provider_id": provider_id,
        "ok": True,
        "auto_refreshed": False,
        "method": "restart-required",
        "action_needed": f"restart {descriptor.display_name} to apply MCP config changes",
    }


def _sync_managed_entries(
    provider_id: str,
    project_root: Path,
    desired_entries: dict[str, tuple[str, McpServerEntry]],
    *,
    managed_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Sync AUDiaGentic-owned MCP entries for one provider.

    Thin MCP adapter over the generic fragment reconciler
    (foundation/toolchains/fragments.py): the store is the descriptor's
    reader/writer/remover trio, the owner scope is the provider id, and the
    ownership registry is the existing managed-mcp-servers.json (format
    unchanged). When ``managed_ids`` is ``None``, all managed entries for
    the provider are synced; a non-empty set touches only those ids.
    """
    descriptor = _descriptor(provider_id)
    spec = descriptor.mcp_config
    if spec is None:
        return {"provider_id": provider_id, "ok": True, "skipped": "no mcp_config defined"}

    config_path = _resolve_mcp_path(spec, project_root)
    store = FragmentStore(read=spec.reader, write=spec.writer, remove=spec.remover)
    outcome = reconcile_fragments(
        store,
        config_path,
        provider_id,
        desired_entries,
        registry_load=lambda: load_managed_mcp_registry(project_root),
        registry_save=lambda registry: save_managed_mcp_registry(project_root, registry),
        managed_ids=managed_ids,
    )

    result: dict[str, Any] = {
        "provider_id": provider_id,
        "ok": outcome.ok,
        "config_path": str(config_path),
        "updated": outcome.updated,
        "removed": outcome.removed,
        "collisions": outcome.collisions,
    }
    if outcome.changed:
        result.update(reload_provider_mcp(provider_id, project_root))
    else:
        result.update({"auto_refreshed": True, "method": "no-op"})
    return result


def sync_managed_provider_mcp(
    provider_id: str,
    project_root: Path,
    desired_entries: dict[str, tuple[str, McpServerEntry]],
) -> dict[str, Any]:
    """Sync AUDiaGentic-owned MCP entries for one provider.

    Ownership is tracked in a small registry keyed by stable managed_id. Unknown
    entries in the provider config are preserved. Renames are handled by moving
    the owned entry from the old name to the new one.
    """
    return _sync_managed_entries(provider_id, project_root, desired_entries)


def sync_managed_provider_mcp_subset(
    provider_id: str,
    project_root: Path,
    desired_entries: dict[str, tuple[str, McpServerEntry]],
    *,
    managed_ids: set[str],
) -> dict[str, Any]:
    """Sync only selected AUDiaGentic-owned MCP entries for one provider.

    Unlike full-provider reconciliation, this only touches entries whose
    managed ids are listed in `managed_ids`. Other managed entries owned by
    different components stay untouched.
    """
    return _sync_managed_entries(
        provider_id, project_root, desired_entries, managed_ids=managed_ids
    )


def add_mcp_entry(
    config_path: str | Path,
    server_name: str,
    entry: dict[str, Any],
    *,
    container: tuple[str, ...] = ("mcpServers",),
) -> dict[str, Any]:
    """Add/replace an MCP server entry using generic ConfigPatcher.

    This is the provider-scoped replacement for the foundation-level
    ConfigPatcher.add_mcp_entry which was removed to eliminate domain leakage.
    """
    patcher = ConfigPatcher(config_path)
    change = patcher.set_key((*container, server_name), entry)
    return {
        "config_path": str(config_path),
        "server_name": server_name,
        "artifact_id": change.artifact_id,
        "existed": change.existed,
        "operation": change.operation,
    }


def remove_mcp_entry(
    config_path: str | Path,
    server_name: str,
    *,
    container: tuple[str, ...] = ("mcpServers",),
) -> dict[str, Any]:
    """Remove an MCP server entry using generic ConfigPatcher.

    This is the provider-scoped replacement for the foundation-level
    ConfigPatcher.remove_mcp_entry which was removed to eliminate domain leakage.
    """
    patcher = ConfigPatcher(config_path)
    change = patcher.remove_key((*container, server_name))
    return {
        "config_path": str(config_path),
        "server_name": server_name,
        "artifact_id": change.artifact_id,
        "existed": change.existed,
        "operation": change.operation,
    }


def get_managed_entry_status(
    provider_id: str,
    project_root: Path,
    server_name: str,
    desired_entry: McpServerEntry,
) -> dict[str, Any]:
    """Read the full MCP entry for *server_name* and compare against *desired_entry*.

    Returns a dict with all keys always present:

    - ``ok`` (bool): descriptor resolved and reader succeeded.
    - ``present`` (bool): an entry named *server_name* exists in config.
    - ``matches`` (bool): present AND equal to *desired_entry*.
    - ``config_path`` (str): resolved config file path (or "" if no mcp_config).
    - ``server_name`` (str): the passed server name.
    - ``actual_entry`` (McpServerEntry | None): the entry as read, or None.
    - ``desired_entry``: the passed desired entry.
    - ``reason`` (str): one of 'no mcp_config', 'read failed', 'absent', 'stale', 'match'.

    When the descriptor has no ``mcp_config``, returns ok=False with reason='no mcp_config'
    so callers can treat the entry as ABSENT without crashing.
    """
    _base: dict[str, Any] = {
        "server_name": server_name,
        "desired_entry": desired_entry,
        "actual_entry": None,
    }

    descriptor = get_descriptor(provider_id)
    if descriptor is None or descriptor.mcp_config is None:
        return {
            **_base,
            "ok": False,
            "present": False,
            "matches": False,
            "config_path": "",
            "reason": "no mcp_config",
        }

    spec = descriptor.mcp_config
    config_path = _resolve_mcp_path(spec, project_root)

    try:
        entries = spec.reader(config_path)
    except Exception:
        return {
            **_base,
            "ok": False,
            "present": False,
            "matches": False,
            "config_path": str(config_path),
            "reason": "read failed",
        }

    actual = entries.get(server_name)
    if actual is None:
        return {
            **_base,
            "ok": True,
            "present": False,
            "matches": False,
            "config_path": str(config_path),
            "reason": "absent",
        }

    _base["actual_entry"] = actual
    if actual == desired_entry:
        return {
            **_base,
            "ok": True,
            "present": True,
            "matches": True,
            "config_path": str(config_path),
            "reason": "match",
        }

    return {
        **_base,
        "ok": True,
        "present": True,
        "matches": False,
        "config_path": str(config_path),
        "reason": "stale",
    }
