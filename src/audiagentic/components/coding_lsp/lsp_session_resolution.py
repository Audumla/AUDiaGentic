"""Session acquisition and project/language root resolution for LSP ops.

Owns the shared SessionManager plus the plumbing that turns a file path into
warmed sessions: project/language root walking, server discovery, per-file
server resolution (with auto-enable/auto-install), capability-aware session
picking, and the PATH-refresh helpers used after package installs.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import sys
from pathlib import Path
from typing import Any

from audiagentic.components.coding_lsp.file_matching import file_matches_patterns
from audiagentic.components.coding_lsp.lsp_constants import LANGUAGE_MARKERS
from audiagentic.components.coding_lsp.lsp_lifecycle import LspSession, ServerConfig
from audiagentic.components.coding_lsp.lsp_session_manager import SessionManager
from audiagentic.components.coding_lsp.runtime_resolver import (
    resolve_active_runtime_servers,
)
from audiagentic.components.coding_lsp.uri_utils import file_to_uri

logger = logging.getLogger(__name__)

_session_manager = SessionManager()


def shutdown_all_sessions() -> None:
    _session_manager.shutdown_all()


def _get_session_or_none(
    project_root: Path,
    language: str,
    cfg: ServerConfig,
) -> LspSession | None:
    """Best-effort session acquisition.

    A single broken or missing server should not make unrelated LSP tools fail
    for the whole workspace. Callers that can degrade should use this helper.
    """
    try:
        return _session_manager.get_or_create(project_root, language, cfg)
    except Exception:
        server_id = cfg.server_id or (cfg.command[0] if cfg.command else "unknown")
        logger.warning(
            "Failed to start LSP server %s for %s",
            server_id,
            language,
            exc_info=True,
        )
        return None


def _refresh_path_after_install() -> None:
    """Augment PATH with user-scope entries added by a package manager install.

    On Windows, winget/scoop may add directories to the user ``Environment``
    PATH that the current process does not see until restart. Read that value
    and *append* anything new.

    This must never replace ``os.environ["PATH"]`` with the registry value.
    HKCU holds only the user-scope PATH, so assigning it wholesale discards the
    machine-scope (HKLM) and inherited entries — dropping, for example,
    ``C:\\Program Files\\nodejs``, which then makes every later ``shutil.which``
    lookup for node/npx fail for the remaining life of the process. Registry
    PATH is also typically ``REG_EXPAND_SZ``, so unexpanded tokens such as
    ``%LOCALAPPDATA%`` must be expanded or the appended entries are inert.
    """
    if not sys.platform.startswith("win"):
        return
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment", 0, winreg.KEY_READ) as key:
            path_val, value_type = winreg.QueryValueEx(key, "PATH")
    except Exception:
        return

    if not isinstance(path_val, str) or not path_val:
        return
    if value_type == winreg.REG_EXPAND_SZ:
        path_val = os.path.expandvars(path_val)

    current = [p for p in os.environ.get("PATH", "").split(os.pathsep) if p]
    seen = {p.rstrip("\\/").casefold() for p in current}
    added = [
        entry
        for entry in (e.strip() for e in path_val.split(os.pathsep))
        if entry and entry.rstrip("\\/").casefold() not in seen
    ]
    if added:
        os.environ["PATH"] = os.pathsep.join(current + added)


def _find_binary_after_install(name: str) -> bool:
    """Check if binary is now available after install (may need PATH refresh)."""
    if shutil.which(name):
        return True
    _refresh_path_after_install()
    return shutil.which(name) is not None


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


def resolve_project_root(path: str | Path) -> Path:
    """Resolve project root for a file or directory within a project.

    Walks upward looking for a project marker but stops at the user home
    directory: home is a boundary, not a project root. Without this, any path
    beneath home (e.g. tmp dirs under AppData) would inherit home's LSP config.
    """
    resolved = Path(path).resolve()
    try:
        home = Path.home().resolve()
    except (RuntimeError, OSError):
        home = None
    return _walk_up_to_marker(resolved, ".audiagentic", home)


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


def _auto_install_dependency(project_root: Path, language: str, dependency_id: str) -> None:
    from audiagentic.components.coding_lsp.lsp_config_api import install_lsp_dependencies

    try:
        asyncio.run(install_lsp_dependencies([dependency_id], root=str(project_root)))
        _refresh_path_after_install()
    except Exception:
        logger.warning("Auto-install failed for %s (%s)", language, dependency_id, exc_info=True)


def _resolve_language_servers_for_file(
    file_path: Path,
    project_root: Path,
) -> list[tuple[str, ServerConfig]]:
    """Return all (language, server) pairs that handle this file.

    Ordered: semantic server first per language (resolver order is preserved).
    Auto-enables the language if it's not yet enabled but the extension matches.
    """
    from audiagentic.components.coding_lsp import language_registry as _lr
    from audiagentic.foundation.features.base import FeatureState
    from audiagentic.foundation.features.state import (
        get_feature_state,
        set_feature_state,
    )

    servers_by_lang = discover_servers_multi(project_root)
    matches: list[tuple[str, Any]] = []

    for language, cfgs in servers_by_lang.items():
        for cfg in cfgs:
            if file_matches_patterns(file_path, cfg.file_extensions):
                # Auto-install missing binary for already-configured languages
                binary = cfg.command[0] if cfg.command else None
                if binary and not _find_binary_after_install(binary):
                    spec = _lr.get_language(language)
                    if spec and spec.dependency:
                        _auto_install_dependency(project_root, language, spec.dependency.id)
                matches.append((language, cfg))

    if not matches:
        for lang_id, spec in _lr.all_languages().items():
            if (
                file_matches_patterns(file_path, spec.file_extensions)
                and lang_id not in servers_by_lang
            ):
                state = get_feature_state(project_root, "coding-lsp", "language", lang_id)
                if not state.enabled:
                    set_feature_state(
                        project_root,
                        "coding-lsp",
                        "language",
                        lang_id,
                        FeatureState(enabled=True, options=dict(state.options)),
                    )
                    # Auto-install missing server binary from recipe
                    if spec.dependency:
                        binary = spec.command[0] if spec.command else None
                        if binary and not _find_binary_after_install(binary):
                            _auto_install_dependency(project_root, lang_id, spec.dependency.id)

                    # Sync pre-commit hook for auto-enabled language
                    try:
                        from audiagentic.components.coding_lsp.git_hooks_sync import (
                            _sync_hook_for_language,
                        )

                        coding_lsp_state = get_feature_state(
                            project_root, "coding-lsp", "coding-lsp", "coding-lsp"
                        )
                        if coding_lsp_state.options.get("pre-commit-hooks-enabled", True):
                            _sync_hook_for_language(project_root, lang_id, install=True)
                    except Exception:
                        logger.warning(
                            "Failed to sync pre-commit hook for auto-enabled language",
                            exc_info=True,
                        )

                    servers_by_lang = discover_servers_multi(project_root)
                    for cfg in servers_by_lang.get(lang_id, []):
                        if file_matches_patterns(file_path, cfg.file_extensions):
                            matches.append((lang_id, cfg))

    return matches


def pick_capable(
    project_root: Path,
    file_path: Path,
    method: str,
) -> LspSession | None:
    """Return the first session (for this file's language) that supports method.

    Creates/warms all sessions for the file before checking capability.
    Returns None if no server supports the method.
    """
    for language, cfg in _resolve_language_servers_for_file(file_path, project_root):
        session = _get_session_or_none(project_root, language, cfg)
        if session is None:
            continue
        if session.has_capability(method):
            return session
    return None


def all_sessions_for_file(
    project_root: Path,
    file_path: Path,
) -> list[LspSession]:
    """Return all warmed sessions that handle this file (across all servers)."""
    sessions = []
    for language, cfg in _resolve_language_servers_for_file(file_path, project_root):
        session = _get_session_or_none(project_root, language, cfg)
        if session is not None:
            sessions.append(session)
    return sessions


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
    errors: list[str] = []
    for language, cfg in language_servers:
        session = _get_session_or_none(project_root, language, cfg)
        if session is None:
            errors.append(cfg.server_id or "unknown")
            continue
        session.sync_document(uri, text, _lang_to_id(language))
        if fallback is None:
            fallback = session
        if method and session.has_capability(method):
            sessions_for_method.append(session)

    if fallback is None:
        detail = f" (failed servers: {', '.join(errors)})" if errors else ""
        return {"error": f"No working language server for {file}{detail}"}, uri

    if sessions_for_method:
        # Prefer semantic servers (pyright, tsserver, etc.) over linters (ruff, etc.)
        # Heuristic: servers with "langserver" or "analyzer" in command are semantic
        def _server_priority(session: Any) -> int:
            cmd = session.server_config.command
            cmd_str = " ".join(cmd).lower()
            if any(kw in cmd_str for kw in ("langserver", "analyzer", "tsserver")):
                return 0  # Highest priority: semantic server
            if any(kw in cmd_str for kw in ("ruff", "clippy", "eslint")):
                return 2  # Lowest priority: linter
            return 1  # Unknown server: medium priority

        sessions_for_method.sort(key=_server_priority)
        chosen = sessions_for_method[0]
    else:
        chosen = fallback
    return chosen, uri


def _lang_to_id(language: str) -> str:
    from audiagentic.components.coding_lsp import language_registry

    spec = language_registry.get_language(language)
    return spec.language_id if spec else language
