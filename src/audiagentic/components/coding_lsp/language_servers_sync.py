"""Language server projection sync from the LSP component."""
from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

from audiagentic.components.coding_lsp import language_registry
from audiagentic.components.coding_lsp.runtime_resolver import (
    active_language_bindings,
    active_lsp_implementation,
    resolve_active_runtime_servers,
)
from audiagentic.components.providers.providers_api import (
    LanguageServerEntry,
    ManagedMcpEntry,
    ManagedMcpRequest,
    adopt_legacy_mcp_ownership,
    manage_mcp_entries_all,
)
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

_COMPONENT_ID = "coding-lsp"
_MCP_OWNERSHIP_SCOPE = "coding-lsp/ag-lsp"

logger = logging.getLogger(__name__)


def _runtime_server_args(project_root: Path) -> tuple[str, ...]:
    args: list[str] = []
    for language, servers in resolve_active_runtime_servers(project_root).items():
        for server in servers:
            command = ",".join(server.command)
            if command:
                args.append(f"{language}:{command}")
    return tuple(args)


def _generic_mcp_projection_spec(implementation: str) -> dict[str, Any]:
    descriptor = get_implementation(_COMPONENT_ID, implementation)
    if descriptor is None:
        return {}
    projection = descriptor.raw.get("projection") or {}
    if not isinstance(projection, dict):
        return {}
    spec = projection.get("generic-mcp") or {}
    return _ensure_dict(spec)


def _generic_mcp_managed_ids() -> set[str]:
    ids: set[str] = set()
    for descriptor in get_implementations(_COMPONENT_ID).values():
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


def _to_managed_mcp_entry(
    managed_id: str, name: str, entry: McpServerEntry,
) -> ManagedMcpEntry:
    """Convert an McpServerEntry projection to a ManagedMcpEntry."""
    cmd = entry.command or None
    return ManagedMcpEntry(
        managed_id=managed_id,
        name=name,
        command=cmd,
        args=entry.args,
        env=tuple(sorted(entry.env.items())) if entry.env else (),
        url=entry.url,
        headers=tuple(sorted(entry.headers.items())) if entry.headers else (),
        transport=("http" if entry.transport == "http" else ("sse" if entry.transport == "sse" else None)),
    )


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
        # Runtime-bridged server (e.g. Blackwell agent-lsp): explicit command + runtime args.
        command = spec.get("command")
        if not isinstance(command, str) or not command:
            return {}
        cmd = command
        raw_args = spec.get("args", ())
        args = tuple(str(a) for a in raw_args) if isinstance(raw_args, list) else ()
        if spec.get("args-from-runtime-servers") is True:
            args = (*args, *_runtime_server_args(project_root))
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


def _blackwell_agent_lsp_mcp_args_projection(project_root: Path) -> dict[str, tuple[str, McpServerEntry]]:
    """Writer for blackwell-agent-lsp.mcp-args bindings: produce MCP args from runtime servers."""
    implementation = "blackwell-agent-lsp"
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
        args = _runtime_server_args(project_root)
    env = {}

    return {
        str(managed_id): (
            str(name),
            McpServerEntry(name=str(name), command=cmd, args=args, env=env),
        )
    }


def _register_builtin_binding_writers() -> None:
    register_binding_writer(
        _COMPONENT_ID,
        "coding-lsp.lsp-json",
        _lsp_json_language_server_projection,
        projection_kind="language-server",
    )
    register_binding_writer(
        _COMPONENT_ID,
        "blackwell-agent-lsp.mcp-args",
        _blackwell_agent_lsp_mcp_args_projection,
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
    for (implementation, _feature_kind, _feature), binding in get_bindings(_COMPONENT_ID).items():
        if implementation != active_implementation:
            continue
        writer_key = binding.projection_writer_key
        if not writer_key or writer_key in seen_writer_keys:
            continue
        writer = get_binding_writer(_COMPONENT_ID, writer_key, projection_kind="generic-mcp")
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
                _COMPONENT_ID,
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

    from audiagentic.components.providers.providers_api import (
        LanguageServerProjectionRequest,
        manage_language_servers_all,
    )

    request = LanguageServerProjectionRequest(entries=configured)
    results = manage_language_servers_all(
        project_root,
        mode="apply",
        request=request,
    )
    synced: list[str] = []
    skipped: list[str] = []
    for result in results:
        if result.ok and result.supported:
            synced.append(result.provider_id)
        else:
            skipped.append(result.provider_id)

    return {
        "ok": True,
        "synced": synced,
        "skipped": skipped,
        "servers": list(configured.keys()),
    }


def sync_generic_lsp_mcp_to_providers(project_root: Path) -> dict[str, Any]:
    """Sync selected generic LSP MCP projection to provider configs."""
    desired_entry = _generic_lsp_projection_for_active_implementation(project_root)
    # Migrate registry scope from legacy provider_id to scoped key before apply
    adopt_legacy_mcp_ownership(
        project_root,
        ownership_scope=_MCP_OWNERSHIP_SCOPE,
        managed_ids=frozenset(_generic_mcp_managed_ids()),
    )

    entries = tuple(
        _to_managed_mcp_entry(mid, name, entry)
        for mid, (name, entry) in desired_entry.items()
    )
    request = ManagedMcpRequest(ownership_scope=_MCP_OWNERSHIP_SCOPE, entries=entries)
    results = manage_mcp_entries_all(
        project_root,
        mode="apply",
        request=request,
    )
    synced: list[str] = []
    skipped: list[str] = []
    for result in results:
        if result.ok and result.supported:
            synced.append(result.provider_id or "")
        else:
            skipped.append(result.provider_id or "")

    return {
        "ok": True,
        "synced": synced,
        "skipped": skipped,
        "mcp_command_status": _mcp_command_status(desired_entry),
    }


def provision_provider_lsp_support(project_root: Path) -> dict[str, Any]:
    """Configure provider-specific LSP support for providers that self-provide LSP."""
    from audiagentic.components.providers.providers_api import (
        SelfProvidedLspRequest,
        manage_self_provided_lsp_all,
    )

    results = manage_self_provided_lsp_all(
        project_root,
        mode="apply",
        request=SelfProvidedLspRequest(project_root=str(project_root)),
    )
    return {
        "ok": True,
        "provisioned": [r.provider_id for r in results if r.ok],
        "skipped": [r.provider_id for r in results if not r.ok],
    }


def prune_language_servers_from_providers(project_root: Path) -> dict[str, Any]:
    """Publish request to remove coding-lsp language server entries from providers.

    Used on component disable/uninstall, so it prunes *every* supported language,
    not just the currently-active set: by the time this fires the feature state
    may already be cleared (``resolve_active_runtime_servers`` would be empty),
    which would otherwise orphan previously-projected entries in provider configs.
    The per-provider removers are idempotent (no-op when the language is absent).
    """
    languages = list(language_registry.all_languages().keys())
    from audiagentic.components.providers.providers_api import (
        LanguageServerProjectionRequest,
        manage_language_servers_all,
    )

    request = LanguageServerProjectionRequest(
        entries={lang: LanguageServerEntry(language=lang, command=[]) for lang in languages}
    )
    results = manage_language_servers_all(
        project_root,
        mode="prune",
        request=request,
    )
    pruned: list[str] = []
    skipped: list[str] = []
    for result in results:
        if result.ok and result.supported:
            pruned.append(result.provider_id)
        else:
            skipped.append(result.provider_id)

    return {
        "ok": True,
        "pruned": pruned,
        "skipped": skipped,
        "languages": languages,
    }


def prune_generic_lsp_mcp_from_providers(project_root: Path) -> dict[str, Any]:
    """Remove coding-lsp managed generic LSP MCP entries from provider configs.

    Uses mode="prune" with empty entries — the engine prunes all entries
    owned by the scope key, so no caller-supplied managed_ids list is needed.
    """
    adopt_legacy_mcp_ownership(
        project_root,
        ownership_scope=_MCP_OWNERSHIP_SCOPE,
        managed_ids=frozenset(_generic_mcp_managed_ids()),
    )

    request = ManagedMcpRequest(ownership_scope=_MCP_OWNERSHIP_SCOPE, entries=())
    results = manage_mcp_entries_all(
        project_root,
        mode="prune",
        request=request,
    )
    pruned: list[str] = []
    skipped: list[str] = []
    for result in results:
        if result.ok and result.supported:
            pruned.append(result.provider_id or "")
        else:
            skipped.append(result.provider_id or "")

    return {
        "ok": True,
        "pruned": pruned,
        "skipped": skipped,
    }
