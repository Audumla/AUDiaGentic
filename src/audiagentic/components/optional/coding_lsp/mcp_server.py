"""LSP code intelligence MCP server.

Pushed to all provider surfaces. Provides semantic code intelligence tools
powered by language servers (pyright, tsserver, rust-analyzer, clangd).
"""
from __future__ import annotations

import atexit
from pathlib import Path
from typing import Any

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    FastMCP = None  # type: ignore[misc, assignment]

from audiagentic.components.optional.coding_lsp.config import (
    detect_project_languages,
    merge_server_configs,
    read_lsp_config,
    resolve_server_for_file,
)
from audiagentic.components.optional.coding_lsp.session_manager import SessionManager

_session_manager = SessionManager()
mcp = FastMCP("lsp-mcp") if FastMCP else None  # type: ignore[call-arg]


def _teardown() -> None:
    _session_manager.shutdown_all()


atexit.register(_teardown)


def _parse_position(pos: str) -> tuple[int, int]:
    """Parse 'line:column' string to 0-based (line, character)."""
    parts = pos.split(":")
    line = int(parts[0]) - 1  # 1-based to 0-based
    character = int(parts[1]) - 1 if len(parts) > 1 else 0
    return line, character


def _file_to_uri(file_path: str | Path) -> str:
    """Convert file path to file:// URI."""
    return Path(file_path).resolve().as_uri()


# ── MCP tools ───────────────────────────────────────────────────────────────

@mcp.tool()  # type: ignore[operator]
def lsp_symbols(query: str, root: str = ".") -> list[dict[str, Any]]:
    """Search for workspace-level symbols matching a query."""
    project_root = Path(root).resolve()
    lsp_path = project_root / ".coding-lsp" / "lsp.json"
    explicit = read_lsp_config(lsp_path)
    detected = detect_project_languages(project_root)
    servers = merge_server_configs(explicit, detected)
    results: list[dict[str, Any]] = []
    for language, server in servers.items():
        try:
            session = _session_manager.get_or_create(project_root, language, server)
            syms = session.workspace_symbol(query)
            results.extend(syms)
        except Exception as exc:
            results.append({"error": f"{language}: {exc}"})
    return results


@mcp.tool()  # type: ignore[operator]
def lsp_doc_symbols(file: str) -> list[dict[str, Any]]:
    """Get document symbols (outline) for a file."""
    uri = _file_to_uri(file)
    project_root = Path(file).resolve().parent
    server = resolve_server_for_file(file, _discover_servers(project_root))
    if server is None:
        return [{"error": f"No language server for {file}"}]
    language = _find_language_for_server(_discover_servers(project_root), server)
    session = _session_manager.get_or_create(project_root, language, server)
    session.did_open(uri, Path(file).read_text(encoding="utf-8", errors="replace"), _lang_to_id(language), 1)
    return session.document_symbol(uri)


@mcp.tool()  # type: ignore[operator]
def lsp_definition(file: str, position: str) -> list[dict[str, Any]]:
    """Go to definition at a file position. Position format: 'line:column' (1-based)."""
    uri = _file_to_uri(file)
    line, character = _parse_position(position)
    project_root = Path(file).resolve().parent
    server = resolve_server_for_file(file, _discover_servers(project_root))
    if server is None:
        return [{"error": f"No language server for {file}"}]
    language = _find_language_for_server(_discover_servers(project_root), server)
    session = _session_manager.get_or_create(project_root, language, server)
    session.did_open(uri, Path(file).read_text(encoding="utf-8", errors="replace"), _lang_to_id(language), 1)
    return session.definition(uri, line, character)


@mcp.tool()  # type: ignore[operator]
def lsp_hover(file: str, position: str) -> dict[str, Any] | None:
    """Get hover/type information at a file position. Position format: 'line:column' (1-based)."""
    uri = _file_to_uri(file)
    line, character = _parse_position(position)
    project_root = Path(file).resolve().parent
    server = resolve_server_for_file(file, _discover_servers(project_root))
    if server is None:
        return {"error": f"No language server for {file}"}
    language = _find_language_for_server(_discover_servers(project_root), server)
    session = _session_manager.get_or_create(project_root, language, server)
    session.did_open(uri, Path(file).read_text(encoding="utf-8", errors="replace"), _lang_to_id(language), 1)
    return session.hover(uri, line, character)


@mcp.tool()  # type: ignore[operator]
def lsp_references(file: str, position: str, include_declaration: bool = True) -> list[dict[str, Any]]:
    """Find all references to a symbol at a file position. Position format: 'line:column' (1-based)."""
    uri = _file_to_uri(file)
    line, character = _parse_position(position)
    project_root = Path(file).resolve().parent
    server = resolve_server_for_file(file, _discover_servers(project_root))
    if server is None:
        return [{"error": f"No language server for {file}"}]
    language = _find_language_for_server(_discover_servers(project_root), server)
    session = _session_manager.get_or_create(project_root, language, server)
    session.did_open(uri, Path(file).read_text(encoding="utf-8", errors="replace"), _lang_to_id(language), 1)
    return session.references(uri, line, character, include_declaration)


@mcp.tool()  # type: ignore[operator]
def lsp_diagnostics(root: str = ".", fresh: bool = False) -> dict[str, list[dict[str, Any]]]:
    """Get diagnostics for all open files in a project."""
    project_root = Path(root).resolve()
    sessions = _session_manager._sessions.get(str(project_root), {})
    all_diagnostics: dict[str, list[dict[str, Any]]] = {}
    for session in sessions.values():
        all_diagnostics.update(session.get_diagnostics())
    return all_diagnostics


@mcp.tool()  # type: ignore[operator]
def lsp_rename_preview(file: str, position: str, new_name: str) -> dict[str, Any] | None:
    """Preview a rename operation. Returns workspace edit without applying. Position format: 'line:column' (1-based)."""
    uri = _file_to_uri(file)
    line, character = _parse_position(position)
    project_root = Path(file).resolve().parent
    server = resolve_server_for_file(file, _discover_servers(project_root))
    if server is None:
        return {"error": f"No language server for {file}"}
    language = _find_language_for_server(_discover_servers(project_root), server)
    session = _session_manager.get_or_create(project_root, language, server)
    session.did_open(uri, Path(file).read_text(encoding="utf-8", errors="replace"), _lang_to_id(language), 1)
    return session.rename(uri, line, character, new_name)


# ── internal helpers ────────────────────────────────────────────────────────

def _discover_servers(project_root: Path) -> dict[str, Any]:
    lsp_path = project_root / ".coding-lsp" / "lsp.json"
    explicit = read_lsp_config(lsp_path)
    detected = detect_project_languages(project_root)
    return merge_server_configs(explicit, detected)


def _find_language_for_server(servers: dict[str, Any], target) -> str:
    for name, srv in servers.items():
        if srv is target:
            return name
    return "python"


def _lang_to_id(language: str) -> str:
    mapping = {
        "python": "python",
        "typescript": "typescript",
        "rust": "rust",
        "cpp": "cpp",
        "javascript": "javascript",
    }
    return mapping.get(language, language)


def main() -> None:
    """Entry point for harness invocation."""
    if mcp is None:
        raise ImportError("mcp package not installed")
    mcp.run()


if __name__ == "__main__":
    main()
