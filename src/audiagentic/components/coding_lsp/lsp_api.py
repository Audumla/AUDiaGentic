"""Internal LSP service API — protocol operations.

Facade shared by MCP wrappers and in-process callers. URI/position utilities
and result normalization live in uri_utils; session acquisition and
project/language root resolution live in lsp_session_resolution; this module
keeps the public op functions (many routed through one positional dispatcher).
Config/dependency management lives in lsp_config_api.py.
"""
from __future__ import annotations

import logging
from typing import Any

from audiagentic.components.coding_lsp.lsp_constants import (
    FILE_BASENAME_TO_LANGUAGE,
)
from audiagentic.components.coding_lsp.lsp_edit_ops import (  # noqa: F401  (facade re-exports)
    _is_mutation_enabled,
    _require_mutation,
    apply_workspace_edit,
    code_actions,
    format_preview,
    organize_imports_preview,
    rename_preview,
)
from audiagentic.components.coding_lsp.lsp_session_resolution import (  # noqa: F401  (facade re-exports)
    _find_binary_after_install,
    _get_session_or_none,
    _open_file_session,
    _resolve_language_servers_for_file,
    _session_manager,
    _sync_to_providers,
    all_sessions_for_file,
    discover_servers,
    discover_servers_multi,
    pick_capable,
    resolve_language_root,
    resolve_project_root,
    shutdown_all_sessions,
)
from audiagentic.components.coding_lsp.lsp_status_ops import (  # noqa: F401  (facade re-exports)
    changed_diagnostics,
    diagnostics,
    file_diagnostics,
    server_capabilities,
)
from audiagentic.components.coding_lsp.uri_utils import (  # noqa: F401  (facade re-exports)
    file_to_uri,
    normalize_hover,
    normalize_location,
    normalize_symbol,
    normalize_workspace_edit,
    parse_position,
    uri_to_repo_relative,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Positional location ops — one dispatcher for the former 3-line clones
# ---------------------------------------------------------------------------

def _positional_locations_op(
    method: str, session_attr: str, file: str, position: str, *args: Any,
) -> list[dict[str, Any]]:
    """Generic op: open session for method, call it at position, normalize locations."""
    session, uri = _open_file_session(file, method)
    if isinstance(session, dict):
        return [session]
    project_root = resolve_project_root(file)
    line, character = parse_position(position)
    raw = getattr(session, session_attr)(uri, line, character, *args)
    return [normalize_location(loc, project_root) for loc in raw]


def definition(file: str, position: str) -> list[dict[str, Any]]:
    return _positional_locations_op("textDocument/definition", "definition", file, position)


def references(file: str, position: str, include_declaration: bool = True) -> list[dict[str, Any]]:
    return _positional_locations_op(
        "textDocument/references", "references", file, position, include_declaration
    )


def type_definition(file: str, position: str) -> list[dict[str, Any]]:
    return _positional_locations_op("textDocument/typeDefinition", "type_definition", file, position)


def implementation(file: str, position: str) -> list[dict[str, Any]]:
    return _positional_locations_op("textDocument/implementation", "implementation", file, position)


# ---------------------------------------------------------------------------
# Ops with unique shapes
# ---------------------------------------------------------------------------

def workspace_symbols(query: str, root: str = ".") -> list[dict[str, Any]]:
    from audiagentic.components.coding_lsp.lsp_constants import EXTENSION_TO_LANGUAGE
    from audiagentic.components.coding_lsp.lsp_session_resolution import _lang_to_id

    project_root = resolve_project_root(root)
    servers = discover_servers_multi(project_root)
    results: list[dict[str, Any]] = []
    for language, cfgs in servers.items():
        for cfg in cfgs:
            try:
                session = _session_manager.get_or_create(project_root, language, cfg)
                if not session.has_capability("workspace/symbol"):
                    continue
                for f in project_root.iterdir():
                    if f.suffix:
                        ext_lang = EXTENSION_TO_LANGUAGE.get(f.suffix.lstrip("."))
                    else:
                        ext_lang = FILE_BASENAME_TO_LANGUAGE.get(f.name.lower())
                    if ext_lang:
                        try:
                            text = f.read_text(encoding="utf-8", errors="replace")
                            session.sync_document(file_to_uri(f), text, _lang_to_id(ext_lang))
                        except Exception:
                            pass
                raw = session.workspace_symbol(query)
                for s in raw:
                    results.append(normalize_symbol(s, project_root))
            except Exception as exc:
                results.append({"error": f"{language}/{cfg.server_id}: {exc}"})
    return results


def document_symbols(file: str) -> list[dict[str, Any]]:
    session, uri = _open_file_session(file, "textDocument/documentSymbol")
    if isinstance(session, dict):
        return [session]
    project_root = resolve_project_root(file)
    raw = session.document_symbol(uri)
    return [normalize_symbol(s, project_root) for s in raw]


def hover(file: str, position: str) -> dict[str, Any] | None:
    session, uri = _open_file_session(file, "textDocument/hover")
    if isinstance(session, dict):
        return session
    line, character = parse_position(position)
    raw = session.hover(uri, line, character)
    return normalize_hover(raw)


def call_hierarchy(
    file: str, position: str, direction: str = "incoming",
) -> list[dict[str, Any]]:
    session, uri = _open_file_session(file, "textDocument/callHierarchy")
    if isinstance(session, dict):
        return [session]
    project_root = resolve_project_root(file)
    line, character = parse_position(position)
    if direction == "outgoing":
        raw = session.call_hierarchy_outgoing(uri, line, character)
    else:
        raw = session.call_hierarchy_incoming(uri, line, character)
    normalized: list[dict[str, Any]] = []
    for call in raw:
        from_loc = call.get("from", {})
        from_range = from_loc.get("range", from_loc.get("fromRange", {}))
        normalized.append({
            "from": uri_to_repo_relative(from_loc.get("uri", ""), project_root),
            "fromRange": from_range,
            "fromLine": from_range.get("start", {}).get("line", 0),
        })
    return normalized


def type_hierarchy(
    file: str, position: str, direction: str = "supertypes",
) -> list[dict[str, Any]]:
    session, uri = _open_file_session(file, "textDocument/typeHierarchy")
    if isinstance(session, dict):
        return [session]
    project_root = resolve_project_root(file)
    line, character = parse_position(position)
    if direction == "subtypes":
        raw = session.type_hierarchy_subtypes(uri, line, character)
    else:
        raw = session.type_hierarchy_supertypes(uri, line, character)
    normalized: list[dict[str, Any]] = []
    for item in raw:
        loc = item.get("location", {})
        normalized.append({
            "name": item.get("name", ""),
            "kind": item.get("kind", ""),
            "file": uri_to_repo_relative(loc.get("uri", ""), project_root),
            "uri": loc.get("uri", ""),
            "range": loc.get("range", {}),
        })
    return normalized


def symbol_context(file: str, position: str) -> dict[str, Any]:
    session, uri = _open_file_session(file, "textDocument/hover")
    if isinstance(session, dict):
        return session
    project_root = resolve_project_root(file)
    line, character = parse_position(position)
    raw = session.symbol_context(uri, line, character)
    return {
        "hover": normalize_hover(raw.get("hover")),
        "definitions": [normalize_location(loc, project_root) for loc in raw.get("definitions", [])],
        "references": [normalize_location(loc, project_root) for loc in raw.get("references", [])],
        "referenceCount": raw.get("referenceCount", 0),
    }


