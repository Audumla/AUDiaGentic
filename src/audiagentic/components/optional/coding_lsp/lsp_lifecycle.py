"""LSP session lifecycle management.

Handles initialize/initialized handshake, document synchronization, and
high-level LSP requests (definition, hover, references, rename, symbols).
"""
from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .lsp_bridge import LspJsonRpc, _lsp_error

logger = logging.getLogger(__name__)

_LSP_VERSION = "3.17"


def _encode_position(text: str, line: int, character: int, encoding: str = "utf-16") -> tuple[int, int]:
    """Convert a (line, character) position from UTF-8 codepoints to the target encoding.

    LSP positions are UTF-16 code units by default. If the server negotiated UTF-8,
    no conversion is needed. For UTF-16, count surrogate pairs.
    """
    if encoding == "utf-8":
        return (line, character)
    # UTF-16: count code units (surrogate pairs = 2 units each)
    if line < 0 or character < 0:
        return (line, character)
    lines = text.split("\n")
    if line >= len(lines):
        return (line, character)
    line_text = lines[line]
    utf16_char = 0
    for i, ch in enumerate(line_text):
        if i >= character:
            break
        utf16_char += 2 if ord(ch) > 0xFFFF else 1
    return (line, utf16_char)


@dataclass
class ServerConfig:
    """Configuration for a single language server."""
    command: list[str]
    file_extensions: list[str] = field(default_factory=list)
    workspace_config_files: list[str] = field(default_factory=list)
    settings: dict[str, Any] = field(default_factory=dict)
    label: str = ""


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
        self._document_text: dict[str, str] = {}
        self._position_encoding: str = "utf-16"
        self._diagnostics_cache: dict[str, dict[str, Any]] = {}
        self._diagnostics_event = threading.Event()
        self._last_change_version: dict[str, int] = {}

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
        self._position_encoding = result.get("capabilities", {}).get(
            "positionEncoding", "utf-16"
        )
        self.bridge.on_notification("textDocument/publishDiagnostics", self._on_publish_diagnostics)
        return self._capabilities

    def initialized(self) -> None:
        """Signal that initialization is complete."""
        self.bridge.send_notification("initialized", {"isInitialized": True})

    def did_open(self, uri: str, text: str, language_id: str, version: int = 1) -> None:
        """Open a document in the language server."""
        self._opened_docs[uri] = version
        self._document_text[uri] = text
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
        if changes:
            text = changes[-1].get("text")
            if isinstance(text, str):
                self._document_text[uri] = text
        self.bridge.send_notification(
            "textDocument/didChange",
            {
                "textDocument": {"uri": uri, "version": version},
                "contentChanges": changes,
            },
        )

    def sync_document(self, uri: str, text: str, language_id: str) -> None:
        """Open once, then update only when contents change."""
        if uri not in self._opened_docs:
            self.did_open(uri, text, language_id, version=1)
            return
        if self._document_text.get(uri) == text:
            return
        version = self._opened_docs[uri] + 1
        self.did_change(uri, [{"text": text}], version)

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

    def type_definition(
        self, uri: str, line: int, character: int, timeout: float = 15.0,
    ) -> list[dict[str, Any]]:
        """Go to type definition at position."""
        if not self.has_capability("textDocument/typeDefinition"):
            return []
        result = self.bridge.send_request(
            "textDocument/typeDefinition",
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

    def implementation(
        self, uri: str, line: int, character: int, timeout: float = 15.0,
    ) -> list[dict[str, Any]]:
        """Go to implementation at position."""
        if not self.has_capability("textDocument/implementation"):
            return []
        result = self.bridge.send_request(
            "textDocument/implementation",
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

    def call_hierarchy_incoming(
        self, uri: str, line: int, character: int, timeout: float = 15.0,
    ) -> list[dict[str, Any]]:
        """Get incoming calls (callers) for the symbol at position."""
        if not self.has_capability("textDocument/callHierarchy"):
            return []
        items = self.bridge.send_request(
            "textDocument/prepareCallHierarchy",
            {
                "textDocument": {"uri": uri},
                "position": {"line": line, "character": character},
            },
            timeout=timeout,
        )
        if not items or not isinstance(items, list):
            return []
        all_calls: list[dict[str, Any]] = []
        for item in items:
            incoming = self.bridge.send_request(
                "callHierarchy/incomingCalls",
                {"item": item},
                timeout=timeout,
            )
            if isinstance(incoming, list):
                all_calls.extend(incoming)
        return all_calls

    def call_hierarchy_outgoing(
        self, uri: str, line: int, character: int, timeout: float = 15.0,
    ) -> list[dict[str, Any]]:
        """Get outgoing calls (callees) for the symbol at position."""
        if not self.has_capability("textDocument/callHierarchy"):
            return []
        items = self.bridge.send_request(
            "textDocument/prepareCallHierarchy",
            {
                "textDocument": {"uri": uri},
                "position": {"line": line, "character": character},
            },
            timeout=timeout,
        )
        if not items or not isinstance(items, list):
            return []
        all_calls: list[dict[str, Any]] = []
        for item in items:
            outgoing = self.bridge.send_request(
                "callHierarchy/outgoingCalls",
                {"item": item},
                timeout=timeout,
            )
            if isinstance(outgoing, list):
                all_calls.extend(outgoing)
        return all_calls

    def symbol_context(
        self, uri: str, line: int, character: int, timeout: float = 15.0,
    ) -> dict[str, Any]:
        """Combined hover + definition + references summary for the symbol at position."""
        hover_result = self.hover(uri, line, character, timeout=timeout)
        definition_result = self.definition(uri, line, character, timeout=timeout)
        references_result = self.references(uri, line, character, timeout=timeout)
        return {
            "hover": hover_result,
            "definitions": definition_result,
            "references": references_result,
            "referenceCount": len(references_result),
        }

    def code_actions(
        self, uri: str, range: dict[str, Any] | None, only: list[str] | None = None,
        timeout: float = 15.0,
    ) -> list[dict[str, Any]]:
        """Get code actions (quick fixes, refactors) for a range."""
        if not self.has_capability("textDocument/codeAction"):
            return []
        params: dict[str, Any] = {
            "textDocument": {"uri": uri},
            "range": range or {},
            "context": {"diagnostics": [], "only": only or []},
        }
        result = self.bridge.send_request("textDocument/codeAction", params, timeout=timeout)
        return result if isinstance(result, list) else []

    def formatting(
        self, uri: str, options: dict[str, Any] | None = None, timeout: float = 15.0,
    ) -> list[dict[str, Any]]:
        """Get document formatting edits."""
        if not self.has_capability("textDocument/formatting"):
            return []
        params: dict[str, Any] = {
            "textDocument": {"uri": uri},
            "options": options or {"tabSize": 4, "insertSpaces": True},
        }
        result = self.bridge.send_request("textDocument/formatting", params, timeout=timeout)
        return result if isinstance(result, list) else []

    def range_formatting(
        self, uri: str, range: dict[str, Any], options: dict[str, Any] | None = None,
        timeout: float = 15.0,
    ) -> list[dict[str, Any]]:
        """Get range formatting edits."""
        if not self.has_capability("textDocument/rangeFormatting"):
            return []
        params: dict[str, Any] = {
            "textDocument": {"uri": uri},
            "range": range,
            "options": options or {"tabSize": 4, "insertSpaces": True},
        }
        result = self.bridge.send_request("textDocument/rangeFormatting", params, timeout=timeout)
        return result if isinstance(result, list) else []

    def organize_imports(
        self, uri: str, timeout: float = 15.0,
    ) -> dict[str, Any] | None:
        """Get organize imports workspace edit."""
        if not self.has_capability("textDocument/codeAction"):
            return None
        actions = self.code_actions(uri, None, only=["source.organizeImports"], timeout=timeout)
        for action in actions:
            if isinstance(action, dict) and action.get("edit"):
                return action.get("edit")
        return None

    def diagnostics(
        self, min_severity: int = 4, limit: int = 0, timeout: float = 30.0,
    ) -> dict[str, list[dict[str, Any]]]:
        """Pull diagnostics via workspace/diagnostic request (LSP 3.17).

        min_severity: 1=Error, 2=Warning, 3=Information, 4=Hint (default: all)
        limit: max total diagnostics returned, 0 = unlimited
        """
        try:
            result = self.bridge.send_request(
                "workspace/diagnostic",
                {"identifier": None, "previousResultIds": []},
                timeout=timeout,
            )
        except Exception as exc:
            raise _lsp_error(
                "EXT-LSP-008",
                f"Workspace diagnostics request failed",
                details={"error": str(exc)},
            )
        if not isinstance(result, dict):
            return {}
        out: dict[str, list[dict[str, Any]]] = {}
        total = 0
        for item in result.get("items") or []:
            if not isinstance(item, dict) or item.get("kind") != "full":
                continue
            uri = item.get("uri", "")
            diags = [
                d for d in (item.get("items") or [])
                if isinstance(d, dict) and d.get("severity", 1) <= min_severity
            ]
            if diags:
                if limit > 0:
                    remaining = limit - total
                    diags = diags[:remaining]
                out[uri] = diags
                total += len(diags)
                if limit > 0 and total >= limit:
                    break
        return out

    def file_diagnostics(
        self, file_path: str | Path, min_severity: int = 4, timeout: float = 5.0,
    ) -> list[dict[str, Any]]:
        """Get diagnostics for a single file using publishDiagnostics cache.

        Re-syncs disk content to the server buffer, waits for a version-correlated
        publish, then returns cached diagnostics. Fails loud on error.
        """
        uri = Path(file_path).resolve().as_uri()
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
        uri = params.get("uri", "")
        diagnostics = params.get("diagnostics", [])
        version = params.get("version")
        self._diagnostics_cache[uri] = {
            "diagnostics": diagnostics,
            "version": version,
            "timestamp": __import__("time").monotonic(),
        }
        self._diagnostics_event.set()

    def _sync_file_from_disk(self, uri: str) -> None:
        """Re-read disk content and push to server buffer with version bump."""
        path = self._uri_to_path(uri)
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise _lsp_error("EXT-LSP-006", f"Cannot read file: {path}", details={"error": str(exc)})

        language_id = self._path_to_language_id(str(path))
        if uri not in self._opened_docs:
            self.did_open(uri, text, language_id, version=1)
            self._last_change_version[uri] = 1
        else:
            if self._document_text.get(uri) == text:
                return
            version = self._opened_docs[uri] + 1
            self.did_change(uri, [{"text": text}], version)
            self._last_change_version[uri] = version

    def _wait_for_publish(self, uri: str, timeout: float = 5.0) -> None:
        """Wait for a version-correlated publishDiagnostics for the given uri."""
        self._diagnostics_event.clear()
        import time as _time
        deadline = _time.monotonic() + timeout
        while _time.monotonic() < deadline:
            cached = self._diagnostics_cache.get(uri, {})
            cached_version = cached.get("version")
            last_change = self._last_change_version.get(uri)
            if cached_version is not None and last_change is not None:
                if cached_version >= last_change:
                    return
            elif cached and cached_version is None:
                if last_change is not None:
                    pass
                elif cached:
                    return
            self._diagnostics_event.wait(timeout=max(0.05, deadline - _time.monotonic()))
            self._diagnostics_event.clear()

    def shutdown(self) -> None:
        """Graceful shutdown of the language server session."""
        self._opened_docs.clear()
        self._document_text.clear()
        self.bridge.shutdown()

    def is_ready(self) -> bool:
        """Return True if the session is initialized and server is alive."""
        return self.bridge.is_alive() and bool(self._capabilities)

    def capabilities(self) -> dict[str, Any]:
        """Return the server's capabilities from initialize result."""
        return dict(self._capabilities)

    def has_capability(self, method: str) -> bool:
        """Check if the server supports a given LSP method."""
        cap_map: dict[str, str] = {
            "textDocument/definition": "textDocument.definition",
            "textDocument/hover": "textDocument.hover",
            "textDocument/references": "textDocument.references",
            "textDocument/rename": "textDocument.rename",
            "textDocument/documentSymbol": "textDocument.documentSymbol",
            "textDocument/typeDefinition": "textDocument.typeDefinition",
            "textDocument/implementation": "textDocument.implementation",
            "textDocument/codeAction": "textDocument.codeAction",
            "textDocument/formatting": "textDocument.formatting",
            "textDocument/rangeFormatting": "textDocument.rangeFormatting",
            "textDocument/completion": "textDocument.completion",
            "textDocument/signatureHelp": "textDocument.signatureHelp",
            "textDocument/inlayHint": "textDocument.inlayHint",
            "textDocument/callHierarchy": "textDocument.callHierarchy",
            "workspace/symbol": "workspace.symbol",
            "workspace/diagnostic": "workspace.diagnostic",
        }
        cap_path = cap_map.get(method)
        if not cap_path:
            return True
        parts = cap_path.split(".")
        obj = self._capabilities
        for part in parts:
            if not isinstance(obj, dict) or part not in obj:
                return False
            obj = obj[part]
        return bool(obj)

    # ── internal ──────────────────────────────────────────────────────────

    @staticmethod
    def _path_to_language_id(path: str) -> str:
        """Infer LSP language ID from file extension."""
        ext = Path(path).suffix.lower().lstrip(".")
        mapping = {
            "py": "python", "pyi": "python",
            "ts": "typescript", "tsx": "typescriptreact",
            "js": "javascript", "jsx": "javascriptreact",
            "rs": "rust",
            "c": "c", "h": "c",
            "cpp": "cpp", "cxx": "cpp", "cc": "cpp",
            "hpp": "cpp", "hxx": "cpp", "hh": "cpp",
        }
        return mapping.get(ext, "plaintext")

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
        """Return client capabilities for LSP initialize.

        Declares every capability the planned tool surface needs. Servers gate
        features on what the client advertises — pyright and typescript-language-server
        will return empty or refuse codeAction, completion, signatureHelp, formatting,
        inlayHint, callHierarchy, typeDefinition, and implementation unless declared here.
        """
        return {
            "textDocument": {
                "definition": {"dynamicRegistration": False},
                "hover": {"dynamicRegistration": False},
                "references": {"dynamicRegistration": False},
                "rename": {"dynamicRegistration": False},
                "documentSymbol": {"dynamicRegistration": False},
                "publishDiagnostics": {"relatedInformation": True},
                "typeDefinition": {"dynamicRegistration": False},
                "implementation": {"dynamicRegistration": False},
                "codeAction": {
                    "dynamicRegistration": False,
                    "codeActionLiteralSupport": {
                        "codeActionKind": {
                            "valueSet": [
                                "", "quickfix", "refactor", "refactor.extract",
                                "refactor.inline", "refactor.rewrite",
                                "source", "source.organizeImports",
                            ]
                        }
                    },
                },
                "completion": {
                    "dynamicRegistration": False,
                    "completionItem": {
                        "snippetSupport": False,
                        "commitCharactersSupport": True,
                        "documentationFormat": ["markdown", "plaintext"],
                    },
                    "completionItemKind": {
                        "valueSet": list(range(1, 26)),
                    },
                },
                "signatureHelp": {
                    "dynamicRegistration": False,
                    "signatureInformation": {
                        "parameterInformation": {
                            "labelOffsetSupport": True,
                        },
                    },
                },
                "formatting": {"dynamicRegistration": False},
                "rangeFormatting": {"dynamicRegistration": False},
                "inlayHint": {"dynamicRegistration": False},
                "callHierarchy": {"dynamicRegistration": False},
            },
            "workspace": {
                "symbol": {"dynamicRegistration": False},
                "workspaceFolders": True,
                "configuration": True,
            },
            "general": {
                "positionEncodings": ["utf-8", "utf-16"],
                "markdown": {
                    "supported": True,
                },
            },
        }
