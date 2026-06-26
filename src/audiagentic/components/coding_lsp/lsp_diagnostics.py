"""Diagnostic handling for LSP sessions.

Extracts diagnostic-related methods from LspSession to reduce god-object size.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from .lsp_bridge import _lsp_error
from .lsp_constants import BATCH_DIAGNOSTIC_CLIS, CLI_SEVERITY

logger = logging.getLogger(__name__)


def _run_batch_cli(
    command: list[str], *, cwd: Path, timeout: float,
) -> subprocess.CompletedProcess[str]:
    """Run batch-diagnostics CLI portably.

    Windows package-manager installs often expose CLIs via `.cmd` shims, which
    fail under a bare argv `Popen` path (`WinError 2`). Route through the shell
    there so PATHEXT resolution works, while keeping direct argv exec elsewhere.
    """
    kwargs = {
        "capture_output": True,
        "text": True,
        "timeout": timeout,
        "cwd": str(cwd),
        "stdin": subprocess.DEVNULL,
        "check": False,
    }
    if os.name == "nt":
        return subprocess.run(
            subprocess.list2cmdline(command),
            shell=True,
            **kwargs,
        )
    return subprocess.run(command, **kwargs)


class LspDiagnostics:
    """Handles diagnostic retrieval for LSP sessions."""

    def __init__(self, session: Any) -> None:
        self._session = session

    @property
    def _bridge(self):
        return self._session.bridge

    @property
    def _capabilities(self):
        return self._session._capabilities

    @property
    def _diagnostics_cache(self):
        return self._session._diagnostics_cache

    @property
    def _diagnostics_event(self):
        return self._session._diagnostics_event

    @property
    def _last_change_version(self):
        return self._session._last_change_version

    @property
    def _canonical_uri(self):
        return self._session._canonical_uri

    @property
    def _uri_to_path(self):
        return self._session._uri_to_path

    @property
    def _project_root(self):
        return self._session.project_root

    def diagnostics(
        self, min_severity: int = 4, limit: int = 0, timeout: float = 30.0,
    ) -> dict[str, list[dict[str, Any]]]:
        """Get workspace-wide diagnostics, keyed by file URI."""
        if self._supports_workspace_diagnostic():
            return self._workspace_diagnostics_via_lsp(min_severity, limit, timeout)
        return self._workspace_diagnostics_via_cli(min_severity, limit, timeout)

    def _workspace_diagnostics_via_lsp(
        self, min_severity: int, limit: int, timeout: float,
    ) -> dict[str, list[dict[str, Any]]]:
        """Pull diagnostics via the workspace/diagnostic request (LSP 3.17)."""
        try:
            result = self._bridge.send_request(
                "workspace/diagnostic",
                {"identifier": None, "previousResultIds": []},
                timeout=timeout,
            )
        except Exception as exc:
            raise _lsp_error(
                "EXT-LSP-008",
                "Workspace diagnostics request failed",
                details={"error": str(exc)},
            )
        if not isinstance(result, dict):
            return {}
        out: dict[str, list[dict[str, Any]]] = {}
        total = 0
        for item in result.get("items") or []:
            if not isinstance(item, dict) or item.get("kind") != "full":
                continue
            uri = self._canonical_uri(item.get("uri", ""))
            diags = [
                d for d in (item.get("items") or [])
                if isinstance(d, dict) and d.get("severity", 1) <= min_severity
            ]
            if diags:
                if limit > 0:
                    diags = diags[: limit - total]
                out[uri] = diags
                total += len(diags)
                if limit > 0 and total >= limit:
                    break
        return out

    def _batch_cli_name(self) -> str | None:
        """Resolve the batch-scan CLI for this session's server, or None."""
        if not self._session.server_config.command:
            return None
        base = Path(self._session.server_config.command[0]).name
        if base.lower().endswith(".exe"):
            base = base[: -len(".exe")]
        return BATCH_DIAGNOSTIC_CLIS.get(base)

    def _workspace_diagnostics_via_cli(
        self, min_severity: int, limit: int, timeout: float,
    ) -> dict[str, list[dict[str, Any]]]:
        """Scan the whole project with the server's batch CLI (e.g. pyright --outputjson)."""
        cli = self._batch_cli_name()
        if cli is None:
            raise _lsp_error(
                "EXT-LSP-004",
                "No workspace diagnostics available: server lacks LSP pull "
                "(diagnosticProvider.workspaceDiagnostics) and has no known batch CLI. "
                "Use lsp_file_diagnostics(file) / lsp_changed_diagnostics(files) instead.",
                details={"server": self._session.server_config.command[:1]},
            )
        try:
            proc = _run_batch_cli(
                [cli, "--outputjson", str(self._project_root)],
                cwd=self._project_root,
                timeout=timeout,
            )
        except FileNotFoundError:
            raise _lsp_error(
                "EXT-LSP-004",
                f"Workspace diagnostics CLI '{cli}' not found on PATH. "
                f"Install it (e.g. 'npm i -g {cli}') or use lsp_file_diagnostics(file).",
                details={"cli": cli},
            )
        except subprocess.TimeoutExpired:
            raise _lsp_error(
                "EXT-LSP-003",
                f"Workspace diagnostics scan timed out after {timeout}s",
                details={"cli": cli, "timeout_s": timeout},
            )
        try:
            report = json.loads(proc.stdout)
        except (json.JSONDecodeError, ValueError) as exc:
            raise _lsp_error(
                "EXT-LSP-008",
                f"Could not parse '{cli} --outputjson' output",
                details={"error": str(exc), "stderr": proc.stderr[:500]},
            )
        out: dict[str, list[dict[str, Any]]] = {}
        total = 0
        for entry in report.get("generalDiagnostics") or []:
            if not isinstance(entry, dict):
                continue
            file = entry.get("file")
            if not file:
                continue
            severity = CLI_SEVERITY.get(entry.get("severity", ""), 4)
            if severity > min_severity:
                continue
            uri = self._canonical_uri(Path(file).resolve().as_uri())
            diag = {
                "severity": severity,
                "message": entry.get("message", ""),
                "range": entry.get("range", {}),
                "code": entry.get("rule", ""),
                "source": cli,
            }
            out.setdefault(uri, []).append(diag)
            total += 1
            if limit > 0 and total >= limit:
                break
        return out

    def file_diagnostics(
        self, file_path: str | Path, min_severity: int = 4, timeout: float = 5.0,
    ) -> list[dict[str, Any]]:
        """Get diagnostics for a single file."""
        if isinstance(file_path, str) and file_path.startswith("file://"):
            uri = file_path
        else:
            uri = Path(file_path).resolve().as_uri()
        uri = self._canonical_uri(uri)

        if self._supports_document_diagnostic():
            return self._file_diagnostics_via_pull(uri, min_severity, timeout)
        return self._file_diagnostics_via_push(uri, min_severity, timeout)

    def _supports_document_diagnostic(self) -> bool:
        """True if the server advertises LSP 3.17 document pull diagnostics."""
        provider = self._capabilities.get("diagnosticProvider")
        return provider is not None and provider is not False

    def _file_diagnostics_via_pull(
        self, uri: str, min_severity: int, timeout: float,
    ) -> list[dict[str, Any]]:
        """Pull diagnostics for a single document via textDocument/diagnostic."""
        try:
            result = self._bridge.send_request(
                "textDocument/diagnostic",
                {
                    "textDocument": {"uri": uri},
                    "identifier": None,
                    "previousResultId": None,
                },
                timeout=timeout,
            )
        except Exception as exc:
            raise _lsp_error(
                "EXT-LSP-008",
                "Document pull diagnostics request failed",
                details={"uri": uri, "error": str(exc)},
            )

        if not isinstance(result, dict):
            return []

        kind = result.get("kind")
        if kind == "unchanged":
            cached = self._diagnostics_cache.get(uri, {})
            diags = cached.get("diagnostics", [])
            return [d for d in diags if isinstance(d, dict) and d.get("severity", 1) <= min_severity]

        items = result.get("items") or []
        return [
            d for d in items
            if isinstance(d, dict) and d.get("severity", 1) <= min_severity
        ]

    def _file_diagnostics_via_push(
        self, uri: str, min_severity: int, timeout: float,
    ) -> list[dict[str, Any]]:
        """Get diagnostics via publishDiagnostics push (open/sync + wait)."""
        self._sync_file_from_disk(uri)
        self._wait_for_publish(uri, timeout=timeout)
        cached = self._diagnostics_cache.get(uri, {})
        diags = cached.get("diagnostics", [])
        return [
            d for d in diags
            if isinstance(d, dict) and d.get("severity", 1) <= min_severity
        ]

    def _on_publish_diagnostics(self, params: dict[str, Any] | None) -> None:
        """Handle textDocument/publishDiagnostics notification from server."""
        if params is None:
            return
        uri = self._canonical_uri(params.get("uri", ""))
        diagnostics = params.get("diagnostics", [])
        version = params.get("version")
        self._diagnostics_cache[uri] = {
            "diagnostics": diagnostics,
            "version": version,
            "timestamp": time.monotonic(),
        }
        self._diagnostics_event.set()

    def _sync_file_from_disk(self, uri: str) -> None:
        """Re-read disk content and push to server buffer with version bump."""
        uri = self._canonical_uri(uri)
        path = self._uri_to_path(uri)
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise _lsp_error("EXT-LSP-006", f"Cannot read file: {path}", details={"error": str(exc)})

        language_id = self._session._path_to_language_id(str(path))
        if uri not in self._session._opened_docs:
            self._session.did_open(uri, text, language_id, version=1)
            self._last_change_version[uri] = 1
        else:
            if self._session._document_text.get(uri) == text:
                return
            version = self._session._opened_docs[uri] + 1
            self._session.did_change(uri, [{"text": text}], version)
            self._last_change_version[uri] = version

    def _wait_for_publish(self, uri: str, timeout: float = 5.0) -> None:
        """Wait for a version-correlated publishDiagnostics for the given uri."""
        uri = self._canonical_uri(uri)
        self._diagnostics_event.clear()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            cached = self._diagnostics_cache.get(uri, {})
            cached_version = cached.get("version")
            last_change = self._last_change_version.get(uri)
            if cached_version is not None and last_change is not None:
                if cached_version >= last_change:
                    return
            self._diagnostics_event.wait(timeout=max(0.05, deadline - time.monotonic()))
            self._diagnostics_event.clear()

    def _supports_workspace_diagnostic(self) -> bool:
        """True if the server advertises LSP 3.17 workspace pull diagnostics."""
        provider = self._capabilities.get("diagnosticProvider")
        if isinstance(provider, dict):
            return bool(provider.get("workspaceDiagnostics"))
        return bool(provider)
