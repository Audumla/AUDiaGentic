"""Provider MCP config management — add, remove, list, reload per-provider MCP server entries."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.foundation.contracts.errors import AudiaGenticError

from ..descriptors.base import McpConfigSpec, ProviderDescriptor
from ..descriptors.registry import get_descriptor


def _descriptor(provider_id: str) -> ProviderDescriptor:
    descriptor = get_descriptor(provider_id)
    if descriptor is None:
        raise AudiaGenticError(
            code="PRV-VALIDATION-002",
            kind="validation",
            message="unknown provider",
            details={"provider-id": provider_id},
        )
    return descriptor


def _resolve_mcp_path(spec: McpConfigSpec, project_root: Path) -> Path:
    if callable(spec.config_path):
        return spec.config_path()
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
    from audiagentic.foundation.mcp import McpServerEntry

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
