"""Internal LSP service API — protocol operations.

Shared by MCP wrappers and in-process callers. Config/dependency management
has been moved to lsp_config_api.py.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.components.optional.coding_lsp.coding_lsp_config import (
    CODING_LSP_DIR,
    load_runtime_servers,
    resolve_server_for_file,
)
from audiagentic.components.optional.coding_lsp.lsp_session_manager import SessionManager

_session_manager = SessionManager()


def _sync_to_providers(project_root: Path) -> None:
    """Sync updated lsp.json to provider configs."""
    try:
        from audiagentic.components.optional.coding_lsp.language_servers_sync import (
            sync_generic_lsp_mcp_to_providers,
            sync_language_servers_to_providers,
        )
        sync_language_servers_to_providers(project_root)
        sync_generic_lsp_mcp_to_providers(project_root)
    except Exception:
        import logging
        logging.getLogger(__name__).warning(
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
        if (candidate / CODING_LSP_DIR / "lsp.json").exists():
            return candidate
        if (candidate / ".audiagentic").exists():
            return candidate
    return current


def discover_servers(project_root: str | Path) -> dict[str, Any]:
    resolved_root = resolve_project_root(project_root)
    lsp_path = resolved_root / CODING_LSP_DIR / "lsp.json"
    servers, _, _ = load_runtime_servers(lsp_path)
    return servers


def workspace_symbols(query: str, root: str = ".") -> list[dict[str, Any]]:
    project_root = resolve_project_root(root)
    servers = discover_servers(project_root)
    results: list[dict[str, Any]] = []
    for language, server in servers.items():
        try:
            session = _session_manager.get_or_create(project_root, language, server)
            results.extend(session.workspace_symbol(query))
        except Exception as exc:
            results.append({"error": f"{language}: {exc}"})
    return results


def document_symbols(file: str) -> list[dict[str, Any]]:
    session, uri = _open_file_session(file)
    if isinstance(session, dict):
        return [session]
    return session.document_symbol(uri)


def definition(file: str, position: str) -> list[dict[str, Any]]:
    session, uri = _open_file_session(file)
    if isinstance(session, dict):
        return [session]
    line, character = parse_position(position)
    return session.definition(uri, line, character)


def hover(file: str, position: str) -> dict[str, Any] | None:
    session, uri = _open_file_session(file)
    if isinstance(session, dict):
        return session
    line, character = parse_position(position)
    return session.hover(uri, line, character)


def references(file: str, position: str, include_declaration: bool = True) -> list[dict[str, Any]]:
    session, uri = _open_file_session(file)
    if isinstance(session, dict):
        return [session]
    line, character = parse_position(position)
    return session.references(uri, line, character, include_declaration)


def diagnostics(
    root: str = ".", min_severity: int = 4, limit: int = 0,
) -> dict[str, list[dict[str, Any]]]:
    project_root = resolve_project_root(root)
    return _session_manager.diagnostics(project_root, min_severity=min_severity, limit=limit)


def rename_preview(file: str, position: str, new_name: str) -> dict[str, Any] | None:
    session, uri = _open_file_session(file)
    if isinstance(session, dict):
        return session
    line, character = parse_position(position)
    return session.rename(uri, line, character, new_name)


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
    from audiagentic.components.optional.coding_lsp import language_registry

    spec = language_registry.get_language(language)
    return spec.language_id if spec else language
