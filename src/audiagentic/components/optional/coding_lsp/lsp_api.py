"""Internal LSP service API shared by MCP wrappers and in-process callers."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.components.optional.coding_lsp.coding_lsp_config import (
    _PROBE_SPECS,
    CODING_LSP_DIR,
    available_language_specs,
    detect_project_languages,
    merge_server_configs,
    read_lsp_config,
    resolve_server_for_file,
    write_lsp_config,
)
from audiagentic.components.optional.coding_lsp.lsp_session_manager import SessionManager
from audiagentic.foundation.dependencies import (
    detect_missing,
    load_component_probes,
    load_component_workflow,
)
from audiagentic.foundation.workflow.invocation.steps import SequenceStep

_LSP_PROBES = load_component_probes("coding-lsp")

_session_manager = SessionManager()


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
    """Resolve project root for a file or directory within a project."""
    resolved = Path(path).resolve()
    current = resolved if resolved.is_dir() else resolved.parent
    for candidate in (current, *current.parents):
        if (candidate / CODING_LSP_DIR / "lsp.json").exists():
            return candidate
        if (candidate / ".audiagentic").exists():
            return candidate
    return current


def discover_servers(project_root: str | Path) -> dict[str, Any]:
    resolved_root = resolve_project_root(project_root)
    lsp_path = resolved_root / CODING_LSP_DIR / "lsp.json"
    explicit = read_lsp_config(lsp_path)
    detected = detect_project_languages(resolved_root)
    return merge_server_configs(explicit, detected)


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


def configured_dependency_ids(project_root: Path | None) -> list[str]:
    """Return dependency IDs for languages explicitly configured in lsp.json."""
    if project_root is None:
        return []
    lsp_json = resolve_project_root(project_root) / CODING_LSP_DIR / "lsp.json"
    configured = read_lsp_config(lsp_json)
    dep_ids: list[str] = []
    for lang in configured:
        spec = _PROBE_SPECS.get(lang)
        if spec:
            dep_ids.extend(spec.requires)
    return dep_ids


def config_status(root: str = ".") -> dict[str, Any]:
    project_root = resolve_project_root(root)
    lsp_path = project_root / CODING_LSP_DIR / "lsp.json"
    configured = read_lsp_config(lsp_path)
    deps = _LSP_PROBES
    missing_deps = detect_missing(deps, configured_dependency_ids(project_root))

    language_status: dict[str, dict[str, Any]] = {}
    for lang, cfg in configured.items():
        spec = _PROBE_SPECS.get(lang)
        binary_ok = all(dep_id not in missing_deps for dep_id in (spec.requires if spec else ()))
        language_status[lang] = {
            "configured": True,
            "binary_available": binary_ok,
            "command": cfg.get("command", []),
        }

    return {
        "project_root": str(project_root),
        "languages": language_status,
        "missing_binaries": [lang for lang, status in language_status.items() if not status["binary_available"]],
        "detectable": list(detect_project_languages(project_root).keys()),
    }


def add_language(root: str, language: str) -> dict[str, Any]:
    project_root = resolve_project_root(root)
    lsp_path = project_root / CODING_LSP_DIR / "lsp.json"
    specs = available_language_specs()
    if language not in specs:
        return {"ok": False, "error": f"Unknown language: {language}. Available: {list(specs.keys())}"}
    configured = read_lsp_config(lsp_path)
    configured[language] = specs[language]
    write_lsp_config(lsp_path, configured)
    return {"ok": True, "language": language, "path": str(lsp_path)}


def remove_language(root: str, language: str) -> dict[str, Any]:
    project_root = resolve_project_root(root)
    lsp_path = project_root / CODING_LSP_DIR / "lsp.json"
    configured = read_lsp_config(lsp_path)
    if language not in configured:
        return {"ok": False, "error": f"Language not configured: {language}"}
    del configured[language]
    write_lsp_config(lsp_path, configured)
    return {"ok": True, "language": language, "path": str(lsp_path)}


def list_languages() -> dict[str, Any]:
    specs = available_language_specs()
    return {
        "languages": {
            name: {
                "command": spec["command"],
                "file_extensions": spec.get("file_extensions", []),
            }
            for name, spec in specs.items()
        },
    }


async def install_lsp_dependencies(names: list[str], *, run_with_output) -> dict[str, Any]:
    workflow = load_component_workflow("coding-lsp", action="install")
    filtered = tuple(s for s in workflow.steps if s.id in names) if names else workflow.steps
    seq = SequenceStep(id="install", steps=filtered, fail_fast=False)
    return await run_with_output(
        ctx=None,
        logger="coding-lsp.dependencies.install",
        heartbeat_message="LSP dependency install still running...",
        work=lambda _: seq.run({}),
    )


def list_missing(root: str = ".") -> dict[str, Any]:
    project_root = resolve_project_root(root)
    deps = _LSP_PROBES
    missing = detect_missing(deps, configured_dependency_ids(project_root))
    return {
        "project_root": str(project_root),
        "missing": missing,
        "hint": "Use lsp_install_dependencies to install missing servers." if missing else "All configured language servers are available.",
    }


def _open_file_session(file: str) -> tuple[Any, str]:
    file_path = Path(file).resolve()
    project_root = resolve_project_root(file_path)
    language_server = _resolve_language_server(file_path, project_root)
    if language_server is None:
        return {"error": f"No language server for {file}"}, file_to_uri(file_path)

    language, server = language_server
    uri = file_to_uri(file_path)
    session = _session_manager.get_or_create(project_root, language, server)
    session.did_open(
        uri,
        file_path.read_text(encoding="utf-8", errors="replace"),
        _lang_to_id(language),
        1,
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
    mapping = {
        "python": "python",
        "typescript": "typescript",
        "rust": "rust",
        "cpp": "cpp",
        "javascript": "javascript",
    }
    return mapping.get(language, language)

