"""Edit-shaped LSP ops: code actions, formatting, rename, workspace edits.

Mutation ops are gated by the ag-lsp 'mutation-enabled' implementation option.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.components.coding_lsp.lsp_session_resolution import (
    _open_file_session,
    _resolve_language_servers_for_file,
    _session_manager,
    resolve_project_root,
)
from audiagentic.components.coding_lsp.uri_utils import (
    normalize_workspace_edit,
    parse_position,
)


def _is_mutation_enabled(project_root: Path) -> bool:
    """Check if LSP mutation tools are enabled for the project.

    Reads the mutation-enabled option from the ag-lsp implementation config.
    Defaults to False — mutation tools are opt-in.
    """
    try:
        from audiagentic.foundation.features.state import (
            get_implementation_state,
        )
        state = get_implementation_state(project_root, "coding-lsp", "ag-lsp")
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
