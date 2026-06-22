"""Internal LSP service API — protocol operations.

Shared by MCP wrappers and in-process callers. Config/dependency management
has been moved to lsp_config_api.py.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from audiagentic.components.coding_lsp.coding_lsp_config import (
    resolve_server_for_file,
)
from audiagentic.components.coding_lsp.lsp_session_manager import SessionManager
from audiagentic.components.coding_lsp.runtime_resolver import (
    resolve_active_runtime_servers,
)

logger = logging.getLogger(__name__)

_session_manager = SessionManager()


def _sync_to_providers(project_root: Path) -> None:
    """Sync active feature/runtime LSP projection to provider configs."""
    try:
        from audiagentic.components.coding_lsp.language_servers_sync import (
            sync_generic_lsp_mcp_to_providers,
            sync_language_servers_to_providers,
        )
        sync_language_servers_to_providers(project_root)
        sync_generic_lsp_mcp_to_providers(project_root)
    except Exception:
        logger.warning(
            "Failed to sync language servers to providers after config change",
            exc_info=True,
        )


def shutdown_all_sessions() -> None:
    _session_manager.shutdown_all()


def parse_position(pos: str) -> tuple[int, int]:
    """Parse 'line:column' string to 0-based (line, character)."""
    parts = pos.split(":")
    line = int(parts[0]) - 1
    character = int(parts[1]) - 1 if len(parts) > 1 else 0
    return line, character


def file_to_uri(file_path: str | Path) -> str:
    """Convert file path to file:// URI."""
    return Path(file_path).resolve().as_uri()


def uri_to_repo_relative(uri: str, project_root: Path) -> str:
    """Convert a file:// URI to a repo-relative path string."""
    try:
        path = Path.from_uri(uri)  # type: ignore[attr-defined]
    except (ValueError, AttributeError):
        path = Path(uri.replace("file://", "", 1))
    try:
        return str(path.relative_to(project_root))
    except ValueError:
        return str(path)


def normalize_location(loc: dict[str, Any], project_root: Path) -> dict[str, Any]:
    """Normalize an LSP Location to consistent schema."""
    return {
        "file": uri_to_repo_relative(loc.get("uri", ""), project_root),
        "uri": loc.get("uri", ""),
        "range": loc.get("range", {}),
        "line": loc.get("range", {}).get("start", {}).get("line", 0),
        "character": loc.get("range", {}).get("start", {}).get("character", 0),
    }


def normalize_symbol(sym: dict[str, Any], project_root: Path) -> dict[str, Any]:
    """Normalize an LSP SymbolInformation or DocumentSymbol to consistent schema."""
    kind_map = {
        1: "file", 2: "module", 3: "namespace", 4: "package",
        5: "class", 6: "method", 7: "property", 8: "field",
        9: "constructor", 10: "enum", 11: "interface", 12: "function",
        13: "variable", 14: "constant", 15: "string", 16: "number",
        17: "boolean", 18: "array", 19: "object", 20: "key",
        21: "null", 22: "enum_member", 23: "struct", 24: "event",
        25: "operator", 26: "type_parameter",
    }
    loc = sym.get("location", {})
    return {
        "name": sym.get("name", ""),
        "kind": kind_map.get(sym.get("kind", 0), f"unknown({sym.get('kind', '?')})"),
        "kind_raw": sym.get("kind", 0),
        "file": uri_to_repo_relative(loc.get("uri", ""), project_root),
        "uri": loc.get("uri", ""),
        "range": loc.get("range", sym.get("range", {})),
        "container_name": sym.get("containerName", ""),
        "children": [normalize_symbol(c, project_root) for c in sym.get("children", [])] if "children" in sym else [],
    }


def normalize_hover(hover: dict[str, Any] | None) -> dict[str, Any] | None:
    """Normalize an LSP Hover response to consistent schema."""
    if not hover:
        return None
    contents = hover.get("contents", {})
    if isinstance(contents, dict):
        value = contents.get("value", "")
        kind = contents.get("kind", "plaintext")
    elif isinstance(contents, list):
        first = next((c for c in contents if isinstance(c, dict)), {})
        value = first.get("value", str(contents))
        kind = first.get("kind", "plaintext")
    else:
        value = str(contents)
        kind = "plaintext"
    return {
        "contents": value,
        "format": kind,
        "range": hover.get("range", {}),
    }


def normalize_workspace_edit(edit: dict[str, Any] | None, project_root: Path) -> dict[str, Any] | None:
    """Normalize an LSP WorkspaceEdit to consistent schema."""
    if not edit:
        return None
    changes = edit.get("changes", {})
    normalized_changes: dict[str, list[dict[str, Any]]] = {}
    for uri, ops in changes.items():
        normalized_changes[uri_to_repo_relative(uri, project_root)] = ops
    return {
        "document_changes": edit.get("documentChanges", []),
        "changes": normalized_changes,
        "change_annotations": edit.get("changeAnnotations", {}),
    }


def resolve_project_root(path: str | Path) -> Path:
    """Resolve project root for a file or directory within a project.

    Walks upward looking for a project marker but stops at the user home
    directory: home is a boundary, not a project root. Without this, any path
    beneath home (e.g. tmp dirs under AppData) would inherit home's LSP config.
    """
    resolved = Path(path).resolve()
    current = resolved if resolved.is_dir() else resolved.parent
    try:
        home = Path.home().resolve()
    except (RuntimeError, OSError):
        home = None
    for candidate in (current, *current.parents):
        if home is not None and (candidate == home or candidate in home.parents):
            break  # reached home or above — boundary, not a project root
        # `.audiagentic` is the project marker; lsp.json is a generated cache and
        # must not define project root.
        if (candidate / ".audiagentic").exists():
            return candidate
    return current


# Language-specific project markers for LSP server root resolution
_LANGUAGE_MARKERS: dict[str, list[str]] = {
    "python": ["pyproject.toml", "setup.py", "setup.cfg", "Pipfile", "poetry.lock"],
    "typescript": ["tsconfig.json", "package.json"],
    "javascript": ["package.json"],
    "rust": ["Cargo.toml", "Cargo.lock"],
    "c": ["compile_commands.json", "Makefile", "CMakeLists.txt"],
    "cpp": ["compile_commands.json", "Makefile", "CMakeLists.txt"],
}


def resolve_language_root(path: str | Path, language: str) -> Path:
    """Resolve the language-specific project root for LSP server initialization.

    Some servers (rust-analyzer, typescript-language-server, clangd) need the
    project-marker directory, not the raw cwd. A wrong root yields empty or
    misconfigured results that look like missing capability.
    """
    base_root = resolve_project_root(path)
    markers = _LANGUAGE_MARKERS.get(language, [])
    if not markers:
        return base_root

    resolved = Path(path).resolve()
    current = resolved if resolved.is_dir() else resolved.parent
    try:
        home = Path.home().resolve()
    except (RuntimeError, OSError):
        home = None

    for candidate in (current, *current.parents):
        if home is not None and (candidate == home or candidate in home.parents):
            break
        if candidate == base_root:
            break
        for marker in markers:
            if (candidate / marker).exists():
                return candidate
    return base_root


def discover_servers(project_root: str | Path) -> dict[str, Any]:
    resolved_root = resolve_project_root(project_root)
    return resolve_active_runtime_servers(resolved_root)


def workspace_symbols(query: str, root: str = ".") -> list[dict[str, Any]]:
    project_root = resolve_project_root(root)
    servers = discover_servers(project_root)
    results: list[dict[str, Any]] = []
    for language, server in servers.items():
        try:
            session = _session_manager.get_or_create(project_root, language, server)
            raw = session.workspace_symbol(query)
            results.extend(normalize_symbol(s, project_root) for s in raw)
        except Exception as exc:
            results.append({"error": f"{language}: {exc}"})
    return results


def document_symbols(file: str) -> list[dict[str, Any]]:
    session, uri = _open_file_session(file)
    if isinstance(session, dict):
        return [session]
    project_root = resolve_project_root(file)
    raw = session.document_symbol(uri)
    return [normalize_symbol(s, project_root) for s in raw]


def definition(file: str, position: str) -> list[dict[str, Any]]:
    session, uri = _open_file_session(file)
    if isinstance(session, dict):
        return [session]
    project_root = resolve_project_root(file)
    line, character = parse_position(position)
    raw = session.definition(uri, line, character)
    return [normalize_location(loc, project_root) for loc in raw]


def hover(file: str, position: str) -> dict[str, Any] | None:
    session, uri = _open_file_session(file)
    if isinstance(session, dict):
        return session
    line, character = parse_position(position)
    raw = session.hover(uri, line, character)
    return normalize_hover(raw)


def references(file: str, position: str, include_declaration: bool = True) -> list[dict[str, Any]]:
    session, uri = _open_file_session(file)
    if isinstance(session, dict):
        return [session]
    project_root = resolve_project_root(file)
    line, character = parse_position(position)
    raw = session.references(uri, line, character, include_declaration)
    return [normalize_location(loc, project_root) for loc in raw]


def type_definition(file: str, position: str) -> list[dict[str, Any]]:
    session, uri = _open_file_session(file)
    if isinstance(session, dict):
        return [session]
    project_root = resolve_project_root(file)
    line, character = parse_position(position)
    raw = session.type_definition(uri, line, character)
    return [normalize_location(loc, project_root) for loc in raw]


def implementation(file: str, position: str) -> list[dict[str, Any]]:
    session, uri = _open_file_session(file)
    if isinstance(session, dict):
        return [session]
    project_root = resolve_project_root(file)
    line, character = parse_position(position)
    raw = session.implementation(uri, line, character)
    return [normalize_location(loc, project_root) for loc in raw]


def call_hierarchy(
    file: str, position: str, direction: str = "incoming",
) -> list[dict[str, Any]]:
    session, uri = _open_file_session(file)
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


def symbol_context(file: str, position: str) -> dict[str, Any]:
    session, uri = _open_file_session(file)
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


def code_actions(
    file: str, range_start: str | None = None, range_end: str | None = None,
    only: list[str] | None = None,
) -> list[dict[str, Any]]:
    session, uri = _open_file_session(file)
    if isinstance(session, dict):
        return [session]
    project_root = resolve_project_root(file)
    lsp_range: dict[str, Any] | None = None
    if range_start and range_end:
        sl, sc = parse_position(range_start)
        el, ec = parse_position(range_end)
        lsp_range = {"start": {"line": sl, "character": sc}, "end": {"line": el, "character": ec}}
    raw = session.code_actions(uri, lsp_range, only=only)
    normalized: list[dict[str, Any]] = []
    for action in raw:
        if not isinstance(action, dict):
            continue
        edit = action.get("edit")
        normalized.append({
            "title": action.get("title", ""),
            "kind": action.get("kind", ""),
            "edit": normalize_workspace_edit(edit, project_root) if edit else None,
            "isPreferred": action.get("isPreferred", False),
            "disabled": action.get("disabled"),
        })
    return normalized


def format_preview(
    file: str, range_start: str | None = None, range_end: str | None = None,
) -> dict[str, Any] | None:
    session, uri = _open_file_session(file)
    if isinstance(session, dict):
        return session
    project_root = resolve_project_root(file)
    if range_start and range_end:
        sl, sc = parse_position(range_start)
        el, ec = parse_position(range_end)
        lsp_range = {"start": {"line": sl, "character": sc}, "end": {"line": el, "character": ec}}
        raw = session.range_formatting(uri, lsp_range)
    else:
        raw = session.formatting(uri)
    if not raw:
        return None
    edits: list[dict[str, Any]] = []
    for ed in raw:
        if isinstance(ed, dict):
            text = ed.get("newText", "")
            rng = ed.get("range", {})
            edits.append({
                "range": rng,
                "startLine": rng.get("start", {}).get("line", 0) + 1,
                "startCharacter": rng.get("start", {}).get("character", 0),
                "endLine": rng.get("end", {}).get("line", 0) + 1,
                "endCharacter": rng.get("end", {}).get("character", 0),
                "newText": text,
            })
    return {
        "file": file,
        "edits": edits,
        "editCount": len(edits),
    }


def organize_imports_preview(file: str) -> dict[str, Any] | None:
    session, uri = _open_file_session(file)
    if isinstance(session, dict):
        return session
    project_root = resolve_project_root(file)
    raw = session.organize_imports(uri)
    edit = normalize_workspace_edit(raw, project_root) if raw else None
    if not edit:
        return None
    return {
        "file": file,
        "edit": edit,
    }


def diagnostics(
    root: str = ".", min_severity: int = 4, limit: int = 0,
) -> dict[str, list[dict[str, Any]]]:
    project_root = resolve_project_root(root)
    return _session_manager.diagnostics(project_root, min_severity=min_severity, limit=limit)


def file_diagnostics(
    file: str, min_severity: int = 4, timeout: float = 5.0,
) -> list[dict[str, Any]]:
    """Get diagnostics for a single file using publishDiagnostics cache."""
    file_path = Path(file).resolve()
    project_root = resolve_project_root(file_path)
    language_server = _resolve_language_server(file_path, project_root)
    if language_server is None:
        return [{"source": "coding-lsp", "severity": 1, "code": "EXT-LSP-007",
                  "message": f"No configured language server for {file}",
                  "file": str(file_path), "range": {"start": {"line": 0, "character": 0},
                                                    "end": {"line": 0, "character": 0}}}]
    language, server = language_server
    uri = file_to_uri(file_path)
    session = _session_manager.get_or_create(project_root, language, server)
    return session.file_diagnostics(uri, min_severity=min_severity, timeout=timeout)


def changed_diagnostics(
    files: list[str], min_severity: int = 4, limit: int = 50,
) -> dict[str, list[dict[str, Any]]]:
    """Batch diagnostics for changed files.

    Caller supplies the changed-file list (from git status or job context).
    """
    result: dict[str, list[dict[str, Any]]] = {}
    total = 0
    for file in files:
        if limit > 0 and total >= limit:
            break
        diags = file_diagnostics(file, min_severity=min_severity)
        if diags:
            remaining = (limit - total) if limit > 0 else len(diags)
            result[file] = diags[:remaining]
            total += len(result[file])
    return result


def server_capabilities(file: str) -> dict[str, Any]:
    """Return the language server's capabilities for a given file.

    Shows which LSP methods the server supports, so the agent can decide
    which tools are viable.
    """
    file_path = Path(file).resolve()
    project_root = resolve_project_root(file_path)
    language_server = _resolve_language_server(file_path, project_root)
    if language_server is None:
        return {"error": f"No language server for {file}", "supported": []}
    language, server = language_server
    session = _session_manager.get_or_create(project_root, language, server)
    caps = session.capabilities()
    supported = []
    method_labels = {
        "textDocument/definition": "definition",
        "textDocument/hover": "hover",
        "textDocument/references": "references",
        "textDocument/rename": "rename",
        "textDocument/documentSymbol": "documentSymbol",
        "textDocument/typeDefinition": "typeDefinition",
        "textDocument/implementation": "implementation",
        "textDocument/codeAction": "codeAction",
        "textDocument/formatting": "formatting",
        "textDocument/rangeFormatting": "rangeFormatting",
        "textDocument/completion": "completion",
        "textDocument/signatureHelp": "signatureHelp",
        "textDocument/inlayHint": "inlayHint",
        "textDocument/callHierarchy": "callHierarchy",
        "workspace/symbol": "workspaceSymbol",
        "workspace/diagnostic": "workspaceDiagnostic",
    }
    for method, label in method_labels.items():
        if session.has_capability(method):
            supported.append(label)
    return {
        "language": language,
        "server": server.label if hasattr(server, "label") else str(server),
        "supported": supported,
        "raw": caps,
    }


def rename_preview(file: str, position: str, new_name: str) -> dict[str, Any] | None:
    session, uri = _open_file_session(file)
    if isinstance(session, dict):
        return session
    project_root = resolve_project_root(file)
    line, character = parse_position(position)
    raw = session.rename(uri, line, character, new_name)
    return normalize_workspace_edit(raw, project_root)


def _open_file_session(file: str) -> tuple[Any, str]:
    file_path = Path(file).resolve()
    project_root = resolve_project_root(file_path)
    language_server = _resolve_language_server(file_path, project_root)
    if language_server is None:
        return {"error": f"No language server for {file}"}, file_to_uri(file_path)

    language, server = language_server
    uri = file_to_uri(file_path)
    session = _session_manager.get_or_create(project_root, language, server)
    session.sync_document(
        uri,
        file_path.read_text(encoding="utf-8", errors="replace"),
        _lang_to_id(language),
    )
    return session, uri


def _resolve_language_server(file_path: Path, project_root: Path) -> tuple[str, Any] | None:
    servers = discover_servers(project_root)
    server = resolve_server_for_file(file_path, servers)
    if server is None:
        return None
    for language, candidate in servers.items():
        if candidate == server:
            return language, server
    return None


def _lang_to_id(language: str) -> str:
    from audiagentic.components.coding_lsp import language_registry

    spec = language_registry.get_language(language)
    return spec.language_id if spec else language
