"""Diagnostics and capability-report LSP ops."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.components.coding_lsp.lsp_constants import METHOD_LABELS
from audiagentic.components.coding_lsp.lsp_session_resolution import (
    _get_session_or_none,
    _resolve_language_servers_for_file,
    _session_manager,
    resolve_project_root,
)
from audiagentic.components.coding_lsp.runtime_resolver import (
    resolve_active_runtime_servers,
)
from audiagentic.components.coding_lsp.uri_utils import file_to_uri


def diagnostics(
    root: str = ".", min_severity: int = 4, limit: int = 0,
) -> dict[str, list[dict[str, Any]]]:
    project_root = resolve_project_root(root)
    for language, servers in resolve_active_runtime_servers(project_root).items():
        for cfg in servers:
            _get_session_or_none(project_root, language, cfg)
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
        session = _get_session_or_none(project_root, lang, cfg)
        if session is None:
            servers_out.append({
                "server_id": cfg.server_id,
                "label": cfg.label,
                "supported": [],
                "error": "failed to initialize",
            })
            continue
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


