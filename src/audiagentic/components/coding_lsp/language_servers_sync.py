"""Language server projection sync from the LSP component."""
from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

from audiagentic.components.coding_lsp import language_registry
from audiagentic.components.coding_lsp.language_servers import LanguageServerEntry
from audiagentic.components.coding_lsp.runtime_resolver import (
    active_language_bindings,
    active_lsp_implementation,
    resolve_active_runtime_servers,
)
from audiagentic.foundation.components.ids import COMPONENT_CODING_LSP
from audiagentic.foundation.features.registry import (
    get_binding_writer,
    get_bindings,
    get_implementation,
    get_implementations,
    register_binding_writer,
)
from audiagentic.foundation.io import _ensure_dict
from audiagentic.foundation.mcp import McpServerEntry
from audiagentic.foundation.mcp.launch import component_mcp_launch

logger = logging.getLogger(__name__)


def _agent_lsp_args(project_root: Path) -> tuple[str, ...]:
    args: list[str] = []
    for language, servers in resolve_active_runtime_servers(project_root).items():
        for server in servers:
            command = ",".join(server.command)
            if command:
                args.append(f"{language}:{command}")
    return tuple(args)


def _generic_mcp_projection_spec(implementation: str) -> dict[str, Any]:
    descriptor = get_implementation(COMPONENT_CODING_LSP, implementation)
    if descriptor is None:
        return {}
    projection = descriptor.raw.get("projection") or {}
    if not isinstance(projection, dict):
        return {}
    spec = projection.get("generic-mcp") or {}
    return _ensure_dict(spec)


def _generic_mcp_managed_ids() -> set[str]:
    ids: set[str] = set()
    for descriptor in get_implementations(COMPONENT_CODING_LSP).values():
        projection = descriptor.raw.get("projection") or {}
        if not isinstance(projection, dict):
            continue
        generic_mcp = projection.get("generic-mcp") or {}
        if not isinstance(generic_mcp, dict):
            continue
        managed_id = generic_mcp.get("managed-id")
        if isinstance(managed_id, str) and managed_id:
            ids.add(managed_id)
    return ids


def _generic_mcp_projection(project_root: Path, implementation: str) -> dict[str, tuple[str, McpServerEntry]]:
    spec = _generic_mcp_projection_spec(implementation)
    managed_id = spec.get("managed-id")
    name = spec.get("name")
    if not all(isinstance(item, str) and item for item in (managed_id, name)):
        return {}

    module = spec.get("module")
    if isinstance(module, str) and module:
        # Component MCP server launched through the installed console script.
        raw_args = spec.get("args", ())
        extra = tuple(str(a) for a in raw_args) if isinstance(raw_args, list) else ()
        cmd, subcommand, launch_args = component_mcp_launch(module, extra_args=extra)
        args = (subcommand, *launch_args)
        env = {}
    else:
        # Runtime-bridged server (e.g. agent-lsp): explicit command + runtime args.
        command = spec.get("command")
        if not isinstance(command, str) or not command:
            return {}
        cmd = command
        raw_args = spec.get("args", ())
        args = tuple(str(a) for a in raw_args) if isinstance(raw_args, list) else ()
        if spec.get("args-from-runtime-servers") is True:
            args = (*args, *_agent_lsp_args(project_root))
        env = {}

    return {
        str(managed_id): (
            str(name),
            McpServerEntry(name=str(name), command=cmd, args=args, env=env),
        )
    }


def _lsp_json_language_server_projection(project_root: Path, feature: str) -> dict[str, LanguageServerEntry]:
    servers = resolve_active_runtime_servers(project_root).get(feature, [])
    if not servers:
        return {}
    # Key by language name (feature), not server_id. Provider adapters handle
    # any binary-name mapping internally (e.g. opencode maps python→pyright).
    # Keying by language also lets prune_language_servers_from_providers locate
    # and remove the entry by language name, which is what the remover expects.
    server = servers[0]
    return {
        feature: LanguageServerEntry(
            language=feature,
            command=list(server.command),
            file_extensions=list(server.file_extensions),
            settings=dict(server.settings),
        )
    }


def _agent_lsp_mcp_args_projection(project_root: Path) -> dict[str, tuple[str, McpServerEntry]]:
    """Writer for agent-lsp.mcp-args bindings: produce MCP args from runtime servers."""
    implementation = "agent-lsp"
    spec = _generic_mcp_projection_spec(implementation)
    managed_id = spec.get("managed-id")
    name = spec.get("name")
    if not all(isinstance(item, str) and item for item in (managed_id, name)):
        return {}

    command = spec.get("command")
    if not isinstance(command, str) or not command:
        return {}
    cmd = command
    args = ()
    if spec.get("args-from-runtime-servers") is True:
        args = _agent_lsp_args(project_root)
    env = {}

    return {
        str(managed_id): (
            str(name),
            McpServerEntry(name=str(name), command=cmd, args=args, env=env),
        )
    }


def _register_builtin_binding_writers() -> None:
    register_binding_writer(
        COMPONENT_CODING_LSP,
        "coding-lsp.lsp-json",
        _lsp_json_language_server_projection,
        projection_kind="language-server",
    )
    register_binding_writer(
        COMPONENT_CODING_LSP,
        "agent-lsp.mcp-args",
        _agent_lsp_mcp_args_projection,
        projection_kind="generic-mcp",
    )


_register_builtin_binding_writers()


def _generic_lsp_projection_for_active_implementation(
    project_root: Path,
) -> dict[str, tuple[str, McpServerEntry]]:
    _register_builtin_binding_writers()
    active_implementation = active_lsp_implementation(project_root)
    seen_writer_keys: set[str] = set()
    desired: dict[str, tuple[str, McpServerEntry]] = {}
    for (implementation, _feature_kind, _feature), binding in get_bindings(COMPONENT_CODING_LSP).items():
        if implementation != active_implementation:
            continue
        writer_key = binding.projection_writer_key
        if not writer_key or writer_key in seen_writer_keys:
            continue
        writer = get_binding_writer(COMPONENT_CODING_LSP, writer_key, projection_kind="generic-mcp")
        desired.update(
            writer(project_root) if writer is not None else _generic_mcp_projection(project_root, implementation)
        )
        seen_writer_keys.add(writer_key)
    if not desired:
        desired.update(_generic_mcp_projection(project_root, active_implementation))
    return desired


def _mcp_command_status(desired: dict[str, tuple[str, McpServerEntry]]) -> dict[str, Any]:
    commands = sorted({entry.command for _, entry in desired.values()})
    missing = [command for command in commands if shutil.which(command) is None]
    return {
        "commands": commands,
        "missing": missing,
        "ok": not missing,
    }


def sync_language_servers_to_providers(project_root: Path) -> dict[str, Any]:
    """Sync active language server config projection to provider configs."""
    try:
        _register_builtin_binding_writers()
        configured: dict[str, LanguageServerEntry] = {}
        for binding in active_language_bindings(project_root):
            writer = get_binding_writer(
                COMPONENT_CODING_LSP,
                binding.projection_writer_key,
                projection_kind="language-server",
            )
            if writer is not None:
                configured.update(writer(project_root, binding.feature))
    except Exception:
        logger.warning("Failed to resolve active language server config", exc_info=True)
        return {"ok": True, "synced": [], "skipped": "resolve failed", "errors": ["resolve failed"]}

    if not configured:
        return {"ok": True, "synced": [], "skipped": "no valid configured language servers"}

    from audiagentic.components.providers.services.lsp_projection import (
        sync_language_servers_to_provider_configs,
    )

    return sync_language_servers_to_provider_configs(project_root, configured)


def sync_generic_lsp_mcp_to_providers(project_root: Path) -> dict[str, Any]:
    """Sync selected generic LSP MCP projection to provider configs."""
    desired_entry = _generic_lsp_projection_for_active_implementation(project_root)
    from audiagentic.components.providers.services.lsp_projection import (
        sync_generic_lsp_mcp_to_provider_configs,
    )

    result = sync_generic_lsp_mcp_to_provider_configs(
        project_root,
        desired_entry,
        _generic_mcp_managed_ids(),
    )
    result["mcp_command_status"] = _mcp_command_status(desired_entry)
    return result


def provision_provider_lsp_support(project_root: Path) -> dict[str, Any]:
    """Configure provider-specific LSP support for providers that self-provide LSP."""
    from audiagentic.components.providers.services.lsp_projection import (
        provision_provider_lsp_support as _provision_provider_lsp_support,
    )

    return _provision_provider_lsp_support(project_root)


def prune_language_servers_from_providers(project_root: Path) -> dict[str, Any]:
    """Publish request to remove coding-lsp language server entries from providers.

    Used on component disable/uninstall, so it prunes *every* supported language,
    not just the currently-active set: by the time this fires the feature state
    may already be cleared (``resolve_active_runtime_servers`` would be empty),
    which would otherwise orphan previously-projected entries in provider configs.
    The per-provider removers are idempotent (no-op when the language is absent).
    """
    languages = list(language_registry.all_languages().keys())
    from audiagentic.components.providers.services.lsp_projection import (
        prune_language_servers_from_provider_configs,
    )

    return prune_language_servers_from_provider_configs(project_root, languages)


def prune_generic_lsp_mcp_from_providers(project_root: Path) -> dict[str, Any]:
    """Remove coding-lsp managed generic LSP MCP entries from provider configs."""
    from audiagentic.components.providers.services.lsp_projection import (
        prune_generic_lsp_mcp_from_provider_configs,
    )

    return prune_generic_lsp_mcp_from_provider_configs(
        project_root,
        _generic_mcp_managed_ids(),
    )
