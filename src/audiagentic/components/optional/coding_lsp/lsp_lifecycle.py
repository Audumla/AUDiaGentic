"""LSP session lifecycle management.

Handles initialize/initialized handshake, document synchronization, and
high-level LSP requests (definition, hover, references, rename, symbols).
"""
from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .lsp_bridge import LspJsonRpc

_LSP_VERSION = "3.17"


@dataclass
class ServerConfig:
    """Configuration for a single language server."""
    command: list[str]
    file_extensions: list[str] = field(default_factory=list)
    workspace_config_files: list[str] = field(default_factory=list)
    settings: dict[str, Any] = field(default_factory=dict)
    label: str = ""


@dataclass
class DiagnosticReport:
    """Cached diagnostics for a single file."""
    uri: str
    diagnostics: list[dict[str, Any]]


class LspSession:
    """Manages a single LSP session for one project root and language.

    Lifecycle:
        1. __init__ — stores config, creates bridge
        2. initialize() — sends initialize, waits for capabilities
        3. initialized() — sends initialized notification
        4. did_open() — open documents before queries
        5. definition/hover/references/rename/symbols — send requests
        6. shutdown() — graceful shutdown
    """

    def __init__(self, server_config: ServerConfig, project_root: str | Path) -> None:
        if isinstance(project_root, str):
            project_root = Path(project_root)
        self.server_config = server_config
        self.project_root = project_root.resolve()
        self.root_uri = self._path_to_uri(self.project_root)
        self.bridge = LspJsonRpc()
        self._capabilities: dict[str, Any] = {}
        self._opened_docs: dict[str, int] = {}
        self._diagnostics_callbacks: list[Callable[[dict[str, Any]], None]] = []
        self._diagnostics_cache: dict[str, list[dict[str, Any]]] = {}

    def initialize(self, timeout: float = 30.0) -> dict[str, Any]:
        """Start the language server and complete the initialize handshake."""
        self.bridge.launch_server(
            self.server_config.command,
            cwd=str(self.project_root),
        )
        result = self.bridge.send_request(
            "initialize",
            {
                "processId": os.getpid(),
                "rootUri": self.root_uri,
                "capabilities": self._client_capabilities(),
                "initializationOptions": self.server_config.settings,
                "workspaceFolders": [{"uri": self.root_uri, "name": self.project_root.name}],
            },
            timeout=timeout,
        )
        self._capabilities = result.get("capabilities", {}) if result else {}
        return self._capabilities

    def initialized(self) -> None:
        """Signal that initialization is complete."""
        self.bridge.send_notification("initialized", {"isInitialized": True})

    def did_open(self, uri: str, text: str, language_id: str, version: int = 1) -> None:
        """Open a document in the language server."""
        self._opened_docs[uri] = version
        self.bridge.send_notification(
            "textDocument/didOpen",
            {
                "textDocument": {
                    "uri": uri,
                    "languageId": language_id,
                    "version": version,
                    "text": text,
                }
            },
        )

    def did_change(self, uri: str, changes: list[dict[str, Any]], version: int) -> None:
        """Notify the language server of document changes."""
        self._opened_docs[uri] = version
        self.bridge.send_notification(
            "textDocument/didChange",
            {
                "textDocument": {"uri": uri, "version": version},
                "contentChanges": changes,
            },
        )

    def did_save(self, uri: str, text: str | None = None) -> None:
        """Notify the language server that a document was saved."""
        params: dict[str, Any] = {"textDocument": {"uri": uri}}
        if text is not None:
            params["text"] = text
        self.bridge.send_notification("textDocument/didSave", params)

    def workspace_symbol(self, query: str, timeout: float = 15.0) -> list[dict[str, Any]]:
        """Search for workspace-level symbols matching query."""
        result = self.bridge.send_request(
            "workspace/symbol",
            {"query": query},
            timeout=timeout,
        )
        return result if isinstance(result, list) else []

    def document_symbol(self, uri: str, timeout: float = 15.0) -> list[dict[str, Any]]:
        """Get document-level symbols (outline) for a file."""
        result = self.bridge.send_request(
            "textDocument/documentSymbol",
            {"textDocument": {"uri": uri}},
            timeout=timeout,
        )
        return result if isinstance(result, list) else []

    def definition(self, uri: str, line: int, character: int, timeout: float = 15.0) -> list[dict[str, Any]]:
        """Go to definition at position."""
        result = self.bridge.send_request(
            "textDocument/definition",
            {
                "textDocument": {"uri": uri},
                "position": {"line": line, "character": character},
            },
            timeout=timeout,
        )
        if result is None:
            return []
        if isinstance(result, list):
            return result
        return [result]

    def hover(self, uri: str, line: int, character: int, timeout: float = 15.0) -> dict[str, Any] | None:
        """Get hover information at position."""
        result = self.bridge.send_request(
            "textDocument/hover",
            {
                "textDocument": {"uri": uri},
                "position": {"line": line, "character": character},
            },
            timeout=timeout,
        )
        return result

    def references(
        self, uri: str, line: int, character: int, include_declaration: bool = True, timeout: float = 15.0,
    ) -> list[dict[str, Any]]:
        """Find all references to the symbol at position."""
        result = self.bridge.send_request(
            "textDocument/references",
            {
                "textDocument": {"uri": uri},
                "position": {"line": line, "character": character},
                "context": {"includeDeclaration": include_declaration},
            },
            timeout=timeout,
        )
        return result if isinstance(result, list) else []

    def rename(
        self, uri: str, line: int, character: int, new_name: str, timeout: float = 30.0,
    ) -> dict[str, Any] | None:
        """Get workspace edit for rename (preview, not applied)."""
        result = self.bridge.send_request(
            "textDocument/rename",
            {
                "textDocument": {"uri": uri},
                "position": {"line": line, "character": character},
                "newName": new_name,
            },
            timeout=timeout,
        )
        return result

    def handle_publish_diagnostics(self, callback: Callable[[dict[str, Any]], None]) -> None:
        """Register a callback for publishDiagnostics notifications.

        The callback receives the raw params dict from the notification.
        Diagnostics are also cached internally.
        """
        self._diagnostics_callbacks.append(callback)
        self.bridge._diagnostics_callback = callback  # type: ignore[attr-defined]

    def get_diagnostics(self, uri: str | None = None) -> dict[str, list[dict[str, Any]]]:
        """Return cached diagnostics. If uri given, return only for that file."""
        if uri:
            return {uri: self._diagnostics_cache.get(uri, [])}
        return dict(self._diagnostics_cache)

    def shutdown(self) -> None:
        """Graceful shutdown of the language server session."""
        self._opened_docs.clear()
        self._diagnostics_cache.clear()
        self._diagnostics_callbacks.clear()
        self.bridge.shutdown()

    def is_ready(self) -> bool:
        """Return True if the session is initialized and server is alive."""
        return self.bridge.is_alive() and bool(self._capabilities)

    # ── internal ──────────────────────────────────────────────────────────

    @staticmethod
    def _path_to_uri(path: Path) -> str:
        """Convert a filesystem path to a file:// URI."""
        return path.as_uri()

    @staticmethod
    def _uri_to_path(uri: str) -> Path:
        """Convert a file:// URI to a filesystem path."""
        if uri.startswith("file://"):
            return Path.from_uri(uri)  # type: ignore[attr-defined]
        return Path(uri)

    @staticmethod
    def _client_capabilities() -> dict[str, Any]:
        """Return minimal client capabilities for LSP initialize."""
        return {
            "textDocument": {
                "definition": {"dynamicRegistration": False},
                "hover": {"dynamicRegistration": False},
                "references": {"dynamicRegistration": False},
                "rename": {"dynamicRegistration": False},
                "documentSymbol": {"dynamicRegistration": False},
                "publishDiagnostics": {"relatedInformation": True},
            },
            "workspace": {
                "symbol": {"dynamicRegistration": False},
                "workspaceFolders": True,
            },
        }
