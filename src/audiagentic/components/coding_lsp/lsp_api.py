"""Internal LSP service API — protocol operations.

Shared by MCP wrappers and in-process callers. Config/dependency management
has been moved to lsp_config_api.py.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

from audiagentic.components.coding_lsp.lsp_constants import (
    COMPLETION_KIND_LABELS,
    LANGUAGE_MARKERS,
    METHOD_LABELS,
    SYMBOL_KIND_LABELS,
)
from audiagentic.components.coding_lsp.lsp_lifecycle import LspSession, ServerConfig
from audiagentic.components.coding_lsp.lsp_session_manager import SessionManager
from audiagentic.components.coding_lsp.runtime_resolver import (
    resolve_active_runtime_servers,
)

logger = logging.getLogger(__name__)

_session_manager = SessionManager()


def _is_mutation_enabled(project_root: Path) -> bool:
    """Check if LSP mutation tools are enabled for the project.

    Reads the mutation-enabled option from the ag-lsp implementation config.
    Defaults to False — mutation tools are opt-in.
    """
    try:
        from audiagentic.foundation.components.ids import COMPONENT_CODING_LSP
        from audiagentic.foundation.features.state import (
            get_implementation_state,
        )
        state = get_implementation_state(project_root, COMPONENT_CODING_LSP, "ag-lsp")
        return bool(state.options.get("mutation-enabled", False))
    except Exception:
        return False


def _require_mutation(project_root: Path) -> dict[str, Any] | None:
    """Return an error dict if mutations are not enabled, else None."""
    if not _is_mutation_enabled(project_root):
        return {
            "error": "LSP mutation tools are disabled. Enable via coding-lsp/ag-lsp option 'mutation-enabled: true'.",
            "code": "EXT-LSP-010",
        }
    return None


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
    if uri.startswith("file://"):
        path = Path(url2pathname(unquote(urlparse(uri).path)))
    else:
        path = Path(uri)
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
    loc = sym.get("location", {})
    return {
        "name": sym.get("name", ""),
        "kind": SYMBOL_KIND_LABELS.get(sym.get("kind", 0), f"unknown({sym.get('kind', '?')})"),
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
    return _walk_up_to_marker(resolved, ".audiagentic", home)


# Language-specific project markers for LSP server root resolution


def resolve_language_root(path: str | Path, language: str) -> Path:
    """Resolve the language-specific project root for LSP server initialization.

    Some servers (rust-analyzer, typescript-language-server, clangd) need the
    project-marker directory, not the raw cwd. A wrong root yields empty or
    misconfigured results that look like missing capability.
    """
    base_root = resolve_project_root(path)
    markers = LANGUAGE_MARKERS.get(language, [])
    if not markers:
        return base_root
    resolved = Path(path).resolve()
    try:
        home = Path.home().resolve()
    except (RuntimeError, OSError):
        home = None
    current = resolved if resolved.is_dir() else resolved.parent
    for candidate in (current, *current.parents):
        if home is not None and (candidate == home or candidate in home.parents):
            break
        if candidate == base_root:
            break
        if any((candidate / marker).exists() for marker in markers):
            return candidate
    return base_root


def _walk_up_to_marker(path: Path, marker: str, home: Path | None) -> Path:
    """Walk upward from *path* returning the first ancestor containing *marker*.

    Stops at the user home directory (a boundary, not a project root).
    """
    current = path.resolve() if path.is_dir() else path.parent
    for candidate in (current, *current.parents):
        if home is not None and (candidate == home or candidate in home.parents):
            break
        if (candidate / marker).exists():
            return candidate
    return current


def discover_servers(project_root: str | Path) -> dict[str, Any]:
    """Backward-compat wrapper: returns first server per language (single-server view)."""
    resolved_root = resolve_project_root(project_root)
    multi = resolve_active_runtime_servers(resolved_root)
    return {lang: cfgs[0] for lang, cfgs in multi.items() if cfgs}


def discover_servers_multi(project_root: str | Path) -> dict[str, list[ServerConfig]]:
    """Return dict[language → list[ServerConfig]] for the resolved project root."""
    resolved_root = resolve_project_root(project_root)
    return resolve_active_runtime_servers(resolved_root)


def _resolve_language_servers_for_file(
    file_path: Path, project_root: Path,
) -> list[tuple[str, ServerConfig]]:
    """Return all (language, server) pairs that handle this file.

    Ordered: semantic server first per language (resolver order is preserved).
    Auto-enables the language if it's not yet enabled but the extension matches.
    """
    from audiagentic.components.coding_lsp import language_registry as _lr
    from audiagentic.foundation.components.ids import COMPONENT_CODING_LSP
    from audiagentic.foundation.features.base import FeatureState
    from audiagentic.foundation.features.state import (
        get_feature_state,
        set_feature_state,
    )

    servers_by_lang = discover_servers_multi(project_root)
    ext = file_path.suffix.lower()
    matches: list[tuple[str, Any]] = []

    for language, cfgs in servers_by_lang.items():
        for cfg in cfgs:
            if ext in cfg.file_extensions:
                matches.append((language, cfg))

    if not matches:
        for lang_id, spec in _lr.all_languages().items():
            if ext in spec.file_extensions and lang_id not in servers_by_lang:
                state = get_feature_state(project_root, COMPONENT_CODING_LSP, "language", lang_id)
                if not state.enabled:
                    set_feature_state(
                        project_root, COMPONENT_CODING_LSP, "language", lang_id,
                        FeatureState(enabled=True, options=dict(state.options)),
                    )
                    servers_by_lang = discover_servers_multi(project_root)
                    for cfg in servers_by_lang.get(lang_id, []):
                        if ext in cfg.file_extensions:
                            matches.append((lang_id, cfg))

    return matches


def pick_capable(
    project_root: Path, file_path: Path, method: str,
) -> LspSession | None:
    """Return the first session (for this file's language) that supports method.

    Creates/warms all sessions for the file before checking capability.
    Returns None if no server supports the method.
    """
    for language, cfg in _resolve_language_servers_for_file(file_path, project_root):
        session = _session_manager.get_or_create(project_root, language, cfg)
        if session.has_capability(method):
            return session
    return None


def all_sessions_for_file(
    project_root: Path, file_path: Path,
) -> list[LspSession]:
    """Return all warmed sessions that handle this file (across all servers)."""
    sessions = []
    for language, cfg in _resolve_language_servers_for_file(file_path, project_root):
        sessions.append(_session_manager.get_or_create(project_root, language, cfg))
    return sessions


def workspace_symbols(query: str, root: str = ".") -> list[dict[str, Any]]:
    project_root = resolve_project_root(root)
    servers = discover_servers_multi(project_root)
    results: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for language, cfgs in servers.items():
        for cfg in cfgs:
            try:
                session = _session_manager.get_or_create(project_root, language, cfg)
                if not session.has_capability("workspace/symbol"):
                    continue
                from audiagentic.components.coding_lsp.lsp_constants import EXTENSION_TO_LANGUAGE
                for f in project_root.iterdir():
                    ext_lang = EXTENSION_TO_LANGUAGE.get(f.suffix.lstrip("."))
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


def definition(file: str, position: str) -> list[dict[str, Any]]:
    session, uri = _open_file_session(file, "textDocument/definition")
    if isinstance(session, dict):
        return [session]
    project_root = resolve_project_root(file)
    line, character = parse_position(position)
    raw = session.definition(uri, line, character)
    return [normalize_location(loc, project_root) for loc in raw]


def hover(file: str, position: str) -> dict[str, Any] | None:
    session, uri = _open_file_session(file, "textDocument/hover")
    if isinstance(session, dict):
        return session
    line, character = parse_position(position)
    raw = session.hover(uri, line, character)
    return normalize_hover(raw)


def references(file: str, position: str, include_declaration: bool = True) -> list[dict[str, Any]]:
    session, uri = _open_file_session(file, "textDocument/references")
    if isinstance(session, dict):
        return [session]
    project_root = resolve_project_root(file)
    line, character = parse_position(position)
    raw = session.references(uri, line, character, include_declaration)
    return [normalize_location(loc, project_root) for loc in raw]


def type_definition(file: str, position: str) -> list[dict[str, Any]]:
    session, uri = _open_file_session(file, "textDocument/typeDefinition")
    if isinstance(session, dict):
        return [session]
    project_root = resolve_project_root(file)
    line, character = parse_position(position)
    raw = session.type_definition(uri, line, character)
    return [normalize_location(loc, project_root) for loc in raw]


def implementation(file: str, position: str) -> list[dict[str, Any]]:
    session, uri = _open_file_session(file, "textDocument/implementation")
    if isinstance(session, dict):
        return [session]
    project_root = resolve_project_root(file)
    line, character = parse_position(position)
    raw = session.implementation(uri, line, character)
    return [normalize_location(loc, project_root) for loc in raw]


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


def inlay_hints(
    file: str, range_start: str, range_end: str,
) -> list[dict[str, Any]]:
    session, uri = _open_file_session(file, "textDocument/inlayHint")
    if isinstance(session, dict):
        return [session]
    sl, sc = parse_position(range_start)
    el, ec = parse_position(range_end)
    lsp_range = {"start": {"line": sl, "character": sc}, "end": {"line": el, "character": ec}}
    raw = session.inlay_hints(uri, lsp_range)
    return raw


def signature_help(file: str, position: str) -> dict[str, Any] | None:
    session, uri = _open_file_session(file, "textDocument/signatureHelp")
    if isinstance(session, dict):
        return session
    line, character = parse_position(position)
    raw = session.signature_help(uri, line, character)
    if not raw:
        return None
    sigs = raw.get("signatures", [])
    active = raw.get("activeSignature", 0)
    normalized_sigs: list[dict[str, Any]] = []
    for sig in sigs:
        params = []
        for p in sig.get("parameters", []):
            label = p.get("label", "")
            if isinstance(label, list) and len(label) == 2:
                offset_range = label
                label = f"<offset:{offset_range}>"
            doc = p.get("documentation")
            if isinstance(doc, dict):
                doc_val = doc.get("value", "")
            else:
                doc_val = str(doc or "")
            params.append({
                "label": str(label),
                "documentation": doc_val,
            })
        normalized_sigs.append({
            "label": sig.get("label", ""),
            "documentation": sig.get("documentation", ""),
            "parameters": params,
        })
    return {
        "signatures": normalized_sigs,
        "activeSignature": active,
        "activeParameter": raw.get("activeParameter"),
    }


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


def completion(
    file: str, position: str, trigger_character: str | None = None,
) -> list[dict[str, Any]]:
    session, uri = _open_file_session(file, "textDocument/completion")
    if isinstance(session, dict):
        return [session]
    line, character = parse_position(position)
    raw = session.completion(uri, line, character, trigger_character=trigger_character)
    normalized: list[dict[str, Any]] = []
    kind_map = COMPLETION_KIND_LABELS
    for item in raw:
        if not isinstance(item, dict):
            continue
        doc = item.get("documentation")
        if isinstance(doc, dict):
            doc_val = doc.get("value", "")
        else:
            doc_val = str(doc or "")
        normalized.append({
            "label": item.get("label", ""),
            "kind": kind_map.get(item.get("kind", 0), f"unknown({item.get('kind', '?')})"),
            "detail": item.get("detail", ""),
            "documentation": doc_val,
            "sortText": item.get("sortText", ""),
            "preselect": item.get("preselect", False),
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


def code_actions(
    file: str, range_start: str | None = None, range_end: str | None = None,
    only: list[str] | None = None,
) -> list[dict[str, Any]]:
    session, uri = _open_file_session(file, "textDocument/codeAction")
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
    session, uri = _open_file_session(file, "textDocument/formatting")
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
    session, uri = _open_file_session(file, "textDocument/codeAction")
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
    for language, servers in resolve_active_runtime_servers(project_root).items():
        for cfg in servers:
            _session_manager.get_or_create(project_root, language, cfg)
    return _session_manager.diagnostics(project_root, min_severity=min_severity, limit=limit)


def file_diagnostics(
    file: str, min_severity: int = 4, timeout: float = 5.0,
) -> list[dict[str, Any]]:
    """Get diagnostics for a single file using publishDiagnostics cache."""
    file_path = Path(file).resolve()
    project_root = resolve_project_root(file_path)
    language_servers = _resolve_language_servers_for_file(file_path, project_root)
    if not language_servers:
        return [{"source": "coding-lsp", "severity": 1, "code": "EXT-LSP-007",
                  "message": f"No configured language server for {file}",
                  "file": str(file_path),
                  "range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 0}}}]

    uri = file_to_uri(file_path)
    merged: list[dict[str, Any]] = []
    seen: set[tuple] = set()
    for language, cfg in language_servers:
        session = _session_manager.get_or_create(project_root, language, cfg)
        for d in session.file_diagnostics(uri, min_severity=min_severity, timeout=timeout):
            key = (d.get("source"), d.get("code"), str(d.get("range", {})), d.get("message", "")[:80])
            if key not in seen:
                merged.append(d)
                seen.add(key)
    return merged


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
    language_servers = _resolve_language_servers_for_file(file_path, project_root)
    if not language_servers:
        return {"error": f"No language server for {file}", "supported": []}

    method_labels = METHOD_LABELS

    servers_out: list[dict[str, Any]] = []
    all_supported: set[str] = set()
    language = language_servers[0][0]

    for lang, cfg in language_servers:
        session = _session_manager.get_or_create(project_root, lang, cfg)
        caps = session.capabilities()
        supported = [label for method, label in method_labels.items() if session.has_capability(method)]
        all_supported.update(supported)
        servers_out.append({
            "server_id": cfg.server_id,
            "label": cfg.label,
            "supported": supported,
            "raw": caps,
        })

    return {
        "language": language,
        "servers": servers_out,
        "supported": sorted(all_supported),
    }


def rename_preview(file: str, position: str, new_name: str) -> dict[str, Any] | None:
    file_path = Path(file).resolve()
    project_root = resolve_project_root(file_path)
    block = _require_mutation(project_root)
    if block:
        return block
    session, uri = _open_file_session(file, "textDocument/rename")
    if isinstance(session, dict):
        return session
    line, character = parse_position(position)
    raw = session.rename(uri, line, character, new_name)
    return normalize_workspace_edit(raw, project_root)


def apply_workspace_edit(
    file: str, edit: dict[str, Any], label: str | None = None,
) -> dict[str, Any]:
    """Apply a workspace edit to open documents."""
    file_path = Path(file).resolve()
    project_root = resolve_project_root(file_path)
    block = _require_mutation(project_root)
    if block:
        return block
    language_servers = _resolve_language_servers_for_file(file_path, project_root)
    if not language_servers:
        return {"error": f"No language server for {file}"}
    language, cfg = language_servers[0]
    session = _session_manager.get_or_create(project_root, language, cfg)
    return session.apply_edit(edit, label=label)


def _open_file_session(file: str, method: str = "") -> tuple[Any, str]:
    """Return (session, uri) for the best server for file+method.

    If method is given, picks the first server advertising it.
    Falls back to the first available server if no capability match.
    """
    file_path = Path(file).resolve()
    project_root = resolve_project_root(file_path)
    language_servers = _resolve_language_servers_for_file(file_path, project_root)
    if not language_servers:
        return {"error": f"No language server for {file}"}, file_to_uri(file_path)

    uri = file_to_uri(file_path)
    text = file_path.read_text(encoding="utf-8", errors="replace")

    sessions_for_method: list[Any] = []
    fallback: Any = None
    for language, cfg in language_servers:
        session = _session_manager.get_or_create(project_root, language, cfg)
        session.sync_document(uri, text, _lang_to_id(language))
        if fallback is None:
            fallback = session
        if method and session.has_capability(method):
            sessions_for_method.append(session)

    chosen = sessions_for_method[0] if sessions_for_method else fallback
    return chosen, uri





def _lang_to_id(language: str) -> str:
    from audiagentic.components.coding_lsp import language_registry

    spec = language_registry.get_language(language)
    return spec.language_id if spec else language
