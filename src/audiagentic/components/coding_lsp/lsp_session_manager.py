"""Session manager: lazy LSP session lifecycle per project root and language."""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

from .coding_lsp_config import discover_language_servers
from .lsp_lifecycle import LspSession, ServerConfig

_DEFAULT_IDLE_TIMEOUT = 1800  # 30 minutes
_DIAGNOSTICS_CACHE_TTL = 30.0  # 30 seconds
_CAPABILITIES_CACHE_TTL = 300.0  # 5 minutes


class SessionManager:
    """Manages LSP sessions per project root and language.

    Sessions are created lazily on first request and cached for reuse.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, dict[str, LspSession]] = {}
        self._last_used: dict[str, dict[str, float]] = {}
        self._diagnostics_cache: dict[str, tuple[float, dict[str, list[dict[str, Any]]]]] = {}

    def get_or_create(
        self, project_root: str | Path, language: str, server_config: ServerConfig,
    ) -> LspSession:
        """Get existing session or create new one.

        On first creation, runs the LSP initialize/initialized handshake.
        If an existing session is dead or wedged, it is shut down and replaced.
        """
        root_key = str(Path(project_root).resolve())
        self._ensure_dir(root_key)
        sk = self._session_key(language, server_config)

        if sk in self._sessions[root_key]:
            session = self._sessions[root_key][sk]
            self._touch(root_key, sk)
            if session.is_ready():
                return session
            session.shutdown()

        session = LspSession(server_config, project_root)
        session.initialize()
        session.initialized()
        if server_config.init_wait > 0:
            time.sleep(server_config.init_wait)
        self._sessions[root_key][sk] = session
        self._touch(root_key, sk)
        return session

    def shutdown_session(
        self, project_root: str | Path, language: str, server_id: str = "",
    ) -> None:
        """Shut down a specific language session.

        If server_id is given, shuts down only that server's session.
        If server_id is empty, shuts down ALL sessions for the language.
        """
        root_key = str(Path(project_root).resolve())
        lang_sessions = self._sessions.get(root_key, {})
        to_remove = []
        for sk, session in lang_sessions.items():
            lang_part, _, sid_part = sk.partition(":")
            if lang_part == language and (not server_id or sid_part == server_id):
                session.shutdown()
                to_remove.append(sk)
        for sk in to_remove:
            lang_sessions.pop(sk, None)
            self._last_used.get(root_key, {}).pop(sk, None)

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
            for sk in list(self._sessions[root_key].keys()):
                last = self._last_used.get(root_key, {}).get(sk, 0)
                if now - last > timeout:
                    self._sessions[root_key][sk].shutdown()
                    del self._sessions[root_key][sk]
                    self._last_used.get(root_key, {}).pop(sk, None)
                    shutdown.append(f"{root_key}/{sk}")
        for root_key in list(self._sessions.keys()):
            if not self._sessions[root_key]:
                del self._sessions[root_key]
                self._last_used.pop(root_key, None)
        return shutdown

    def status(self) -> dict[str, Any]:
        """Return status of all sessions."""
        roots: dict[str, list[dict[str, Any]]] = {}
        for root_key, sessions in self._sessions.items():
            root_status: list[dict[str, Any]] = []
            for sk, session in sessions.items():
                language, _, server_id = sk.partition(":")
                last = self._last_used.get(root_key, {}).get(sk, 0)
                root_status.append({
                    "language": language,
                    "server_id": server_id,
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

    def diagnostics(
        self, project_root: str | Path, *, min_severity: int = 4, limit: int = 0, force_refresh: bool = False,
    ) -> dict[str, list[dict[str, Any]]]:
        """Pull diagnostics from all sessions under one project root.

        Uses a TTL cache to avoid redundant LSP queries. Stale entries expire
        by TTL and do not survive file content changes.
        """
        root_key = str(Path(project_root).resolve())
        cache_key = f"{root_key}:{min_severity}:{limit}"

        if not force_refresh:
            cached = self._diagnostics_cache.get(cache_key)
            if cached:
                ts, data = cached
                if time.monotonic() - ts < _DIAGNOSTICS_CACHE_TTL:
                    return data

        all_diagnostics: dict[str, list[dict[str, Any]]] = {}
        for session in self._sessions.get(root_key, {}).values():
            try:
                for uri, diags in session.diagnostics(min_severity=min_severity, limit=limit).items():
                    existing = all_diagnostics.setdefault(uri, [])
                    existing_keys = {
                        (d.get("source"), d.get("code"), str(d.get("range", {})), d.get("message", "")[:80])
                        for d in existing
                    }
                    for d in diags:
                        key = (d.get("source"), d.get("code"), str(d.get("range", {})), d.get("message", "")[:80])
                        if key not in existing_keys:
                            existing.append(d)
                            existing_keys.add(key)
            except Exception as exc:
                logger.warning("Workspace diagnostics failed for session: %s", exc)

        self._diagnostics_cache[cache_key] = (time.monotonic(), all_diagnostics)
        return all_diagnostics

    def invalidate_diagnostics(self, project_root: str | Path | None = None) -> None:
        """Invalidate cached diagnostics.

        Call after file edits to force a fresh diagnostic pull.
        If project_root is None, clears all cached diagnostics.
        """
        if project_root is None:
            self._diagnostics_cache.clear()
            return
        root_key = str(Path(project_root).resolve())
        to_remove = [k for k in self._diagnostics_cache if k.startswith(root_key)]
        for k in to_remove:
            del self._diagnostics_cache[k]

    # ── internal ──────────────────────────────────────────────────────────

    @staticmethod
    def _session_key(language: str, server_config: ServerConfig) -> str:
        sid = server_config.server_id or (server_config.command[0] if server_config.command else "unknown")
        return f"{language}:{sid}"

    def _ensure_dir(self, root_key: str) -> None:
        if root_key not in self._sessions:
            self._sessions[root_key] = {}
            self._last_used[root_key] = {}

    def _touch(self, root_key: str, key: str) -> None:
        self._last_used.setdefault(root_key, {})[key] = time.monotonic()

