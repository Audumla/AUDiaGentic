"""Provider MCP config management — add, remove, list, reload per-provider MCP server entries."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.mcp import McpServerEntry

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
    return project_root / spec.config_path


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
    descriptor = _descriptor(provider_id)
    spec = descriptor.mcp_config
    if spec is None:
        return {"provider_id": provider_id, "ok": True, "skipped": "no mcp_config defined"}

    config_path = _resolve_mcp_path(spec, project_root)
    registry = load_managed_mcp_registry(project_root)
    provider_registry = dict(registry.get(provider_id, {}))
    changed = False
    removed: list[str] = []
    updated: list[str] = []
    collisions: list[dict[str, str]] = []

    current = spec.reader(config_path)

    for managed_id, old_name in list(provider_registry.items()):
        if managed_id in desired_entries:
            continue
        if old_name in current:
            if spec.remover(config_path, old_name):
                removed.append(old_name)
                changed = True
                current.pop(old_name, None)
        provider_registry.pop(managed_id, None)

    def _owner_by_name() -> dict[str, str]:
        return {name: managed_id for managed_id, name in provider_registry.items()}

    for managed_id, (desired_name, entry) in desired_entries.items():
        old_name = provider_registry.get(managed_id)
        owners_by_name = _owner_by_name()

        if desired_name in current and owners_by_name.get(desired_name) not in (None, managed_id):
            collisions.append({
                "managed_id": managed_id,
                "desired_name": desired_name,
                "reason": "name already owned by another managed entry",
            })
            continue

        if desired_name in current and old_name is None and owners_by_name.get(desired_name) is None:
            collisions.append({
                "managed_id": managed_id,
                "desired_name": desired_name,
                "reason": "name already used by external entry",
            })
            continue

        spec.writer(config_path, {desired_name: entry})
        current[desired_name] = entry
        provider_registry[managed_id] = desired_name
        if desired_name not in updated:
            updated.append(desired_name)
        changed = True

        if old_name and old_name != desired_name and old_name in current:
            if spec.remover(config_path, old_name):
                removed.append(old_name)
                current.pop(old_name, None)

    registry[provider_id] = provider_registry
    save_managed_mcp_registry(project_root, registry)

    result: dict[str, Any] = {
        "provider_id": provider_id,
        "ok": not collisions,
        "config_path": str(config_path),
        "updated": updated,
        "removed": removed,
        "collisions": collisions,
    }
    if changed:
        result.update(reload_provider_mcp(provider_id, project_root))
    else:
        result.update({"auto_refreshed": True, "method": "no-op"})
    return result


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
    descriptor = _descriptor(provider_id)
    spec = descriptor.mcp_config
    if spec is None:
        return {"provider_id": provider_id, "ok": True, "skipped": "no mcp_config defined"}

    config_path = _resolve_mcp_path(spec, project_root)
    registry = load_managed_mcp_registry(project_root)
    provider_registry = dict(registry.get(provider_id, {}))
    changed = False
    removed: list[str] = []
    updated: list[str] = []
    collisions: list[dict[str, str]] = []

    current = spec.reader(config_path)
    targeted_existing = {
        managed_id: name
        for managed_id, name in provider_registry.items()
        if managed_id in managed_ids
    }

    for managed_id, old_name in list(targeted_existing.items()):
        if managed_id in desired_entries:
            continue
        if old_name in current:
            if spec.remover(config_path, old_name):
                removed.append(old_name)
                changed = True
                current.pop(old_name, None)
        provider_registry.pop(managed_id, None)

    def _owner_by_name() -> dict[str, str]:
        return {name: managed_id for managed_id, name in provider_registry.items()}

    for managed_id, (desired_name, entry) in desired_entries.items():
        if managed_id not in managed_ids:
            continue

        old_name = provider_registry.get(managed_id)
        owners_by_name = _owner_by_name()

        if desired_name in current and owners_by_name.get(desired_name) not in (None, managed_id):
            collisions.append({
                "managed_id": managed_id,
                "desired_name": desired_name,
                "reason": "name already owned by another managed entry",
            })
            continue

        if desired_name in current and old_name is None and owners_by_name.get(desired_name) is None:
            collisions.append({
                "managed_id": managed_id,
                "desired_name": desired_name,
                "reason": "name already used by external entry",
            })
            continue

        spec.writer(config_path, {desired_name: entry})
        current[desired_name] = entry
        provider_registry[managed_id] = desired_name
        if desired_name not in updated:
            updated.append(desired_name)
        changed = True

        if old_name and old_name != desired_name and old_name in current:
            if spec.remover(config_path, old_name):
                removed.append(old_name)
                current.pop(old_name, None)

    registry[provider_id] = provider_registry
    save_managed_mcp_registry(project_root, registry)

    result: dict[str, Any] = {
        "provider_id": provider_id,
        "ok": not collisions,
        "config_path": str(config_path),
        "updated": updated,
        "removed": removed,
        "collisions": collisions,
    }
    if changed:
        result.update(reload_provider_mcp(provider_id, project_root))
    else:
        result.update({"auto_refreshed": True, "method": "no-op"})
    return result
