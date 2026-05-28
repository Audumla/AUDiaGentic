"""Session manager: lazy LSP session lifecycle per project root and language.

Manages a pool of LspSession instances. Sessions are created on first use
and reused for subsequent requests. Server lifecycle is internal.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from .config import (
    CODING_LSP_DIR,
    discover_language_servers,
    merge_server_configs,
    read_lsp_config,
    resolve_server_for_file,
)
from .lsp_lifecycle import LspSession, ServerConfig

_DEFAULT_IDLE_TIMEOUT = 1800  # 30 minutes


class SessionManager:
    """Manages LSP sessions per project root and language.

    Sessions are created lazily on first request and cached for reuse.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, dict[str, LspSession]] = {}
        self._last_used: dict[str, dict[str, float]] = {}

    def get_or_create(
        self, project_root: str | Path, language: str, server_config: ServerConfig,
    ) -> LspSession:
        """Get existing session or create new one.

        On first creation, runs the LSP initialize/initialized handshake.
        """
        root_key = str(Path(project_root).resolve())
        self._ensure_dir(root_key)

        if language in self._sessions[root_key]:
            session = self._sessions[root_key][language]
            self._touch(root_key, language)
            if session.is_ready():
                return session

        session = LspSession(server_config, project_root)
        session.initialize()
        session.initialized()
        self._sessions[root_key][language] = session
        self._touch(root_key, language)
        return session

    def get_for_file(
        self, project_root: str | Path, file_path: str | Path,
    ) -> tuple[LspSession, str] | None:
        """Find or create a session for a file based on its extension.

        Returns (session, language) or None if no server handles the file.
        """
        root_key = str(Path(project_root).resolve())
        file_path_resolved = Path(file_path).resolve()

        # Check existing sessions first
        for language, session in self._sessions.get(root_key, {}).items():
            server = session.server_config
            if file_path_resolved.suffix in server.file_extensions:
                self._touch(root_key, language)
                return session, language

        # Discover and create
        lsp_path = Path(project_root) / CODING_LSP_DIR / "lsp.json"
        explicit = read_lsp_config(lsp_path)
        detected = {}  # already detected at startup
        servers = merge_server_configs(explicit, detected)
        server = resolve_server_for_file(file_path_resolved, servers)
        if server is None:
            return None

        session = self.get_or_create(project_root, list(servers.keys())[0] if not server.label else self._lang_for_server(servers, server), server)
        return session, list(servers.keys())[0]

    def shutdown_session(self, project_root: str | Path, language: str) -> None:
        """Shut down a specific language session."""
        root_key = str(Path(project_root).resolve())
        session = self._sessions.get(root_key, {}).pop(language, None)
        if session:
            session.shutdown()
        self._last_used.get(root_key, {}).pop(language, None)

    def shutdown_all(self) -> None:
        """Shut down all sessions."""
        for root_key in list(self._sessions.keys()):
            for language in list(self._sessions[root_key].keys()):
                self._sessions[root_key][language].shutdown()
        self._sessions.clear()
        self._last_used.clear()

    def idle_check(self, timeout: float | None = None) -> list[str]:
        """Shut down sessions idle longer than timeout seconds.

        Returns list of shut-down session identifiers.
        """
        if timeout is None:
            timeout = _DEFAULT_IDLE_TIMEOUT
        now = time.monotonic()
        shutdown: list[str] = []
        for root_key in list(self._sessions.keys()):
            for language in list(self._sessions[root_key].keys()):
                last = self._last_used.get(root_key, {}).get(language, 0)
                if now - last > timeout:
                    self._sessions[root_key][language].shutdown()
                    del self._sessions[root_key][language]
                    self._last_used.get(root_key, {}).pop(language, None)
                    shutdown.append(f"{root_key}/{language}")
        # Clean up empty roots
        for root_key in list(self._sessions.keys()):
            if not self._sessions[root_key]:
                del self._sessions[root_key]
                self._last_used.pop(root_key, None)
        return shutdown

    def status(self) -> dict[str, Any]:
        """Return status of all sessions."""
        roots: dict[str, list[dict[str, Any]]] = {}
        for root_key, langs in self._sessions.items():
            root_status: list[dict[str, Any]] = []
            for language, session in langs.items():
                last = self._last_used.get(root_key, {}).get(language, 0)
                root_status.append({
                    "language": language,
                    "ready": session.is_ready(),
                    "last_used_ago_s": round(time.monotonic() - last, 1),
                    "server": session.server_config.command[0] if session.server_config.command else "unknown",
                })
            roots[root_key] = root_status
        return {
            "project_roots": len(roots),
            "total_sessions": sum(len(v) for v in roots.values()),
            "roots": roots,
        }

    def discover_available(self, project_root: str | Path) -> dict[str, bool]:
        """Discover which language servers are available for a project."""
        return discover_language_servers(project_root)

    # ── internal ──────────────────────────────────────────────────────────

    def _ensure_dir(self, root_key: str) -> None:
        if root_key not in self._sessions:
            self._sessions[root_key] = {}
            self._last_used[root_key] = {}

    def _touch(self, root_key: str, language: str) -> None:
        self._last_used.setdefault(root_key, {})[language] = time.monotonic()

    def _lang_for_server(self, servers: dict[str, ServerConfig], target: ServerConfig) -> str:
        for name, srv in servers.items():
            if srv is target:
                return name
        return "unknown"
