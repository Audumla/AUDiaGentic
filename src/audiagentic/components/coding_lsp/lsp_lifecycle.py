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

from .lsp_bridge import LspJsonRpc
from .lsp_diagnostics import LspDiagnostics
from .lsp_protocol_ops import LspProtocolOps
from .uri_utils import canonical_uri, path_to_language_id, path_to_uri, uri_to_path

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


def _ensure_list(result: Any) -> list[dict[str, Any]]:
    """Return result if it's a list, else empty list."""
    return result if isinstance(result, list) else []


@dataclass
class ServerConfig:
    """Configuration for a single language server."""
    command: list[str]
    file_extensions: list[str] = field(default_factory=list)
    workspace_config_files: list[str] = field(default_factory=list)
    settings: dict[str, Any] = field(default_factory=dict)
    label: str = ""
    server_id: str = ""
    init_wait: float = 0.0


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
        self._protocol_ops = LspProtocolOps(self)
        self._diagnostics_handler = LspDiagnostics(self)

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
                "workDoneProgress": True,
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
        uri = self._canonical_uri(uri)
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
        uri = self._canonical_uri(uri)
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
        uri = self._canonical_uri(uri)
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
        return self._protocol_ops.workspace_symbol(query, timeout)

    def document_symbol(self, uri: str, timeout: float = 15.0) -> list[dict[str, Any]]:
        return self._protocol_ops.document_symbol(uri, timeout)

    def definition(self, uri: str, line: int, character: int, timeout: float = 15.0) -> list[dict[str, Any]]:
        return self._protocol_ops.definition(uri, line, character, timeout)

    def hover(self, uri: str, line: int, character: int, timeout: float = 15.0) -> dict[str, Any] | None:
        return self._protocol_ops.hover(uri, line, character, timeout)

    def references(self, uri: str, line: int, character: int, include_declaration: bool = True, timeout: float = 15.0) -> list[dict[str, Any]]:
        return self._protocol_ops.references(uri, line, character, include_declaration, timeout)

    def rename(self, uri: str, line: int, character: int, new_name: str, timeout: float = 30.0) -> dict[str, Any] | None:
        return self._protocol_ops.rename(uri, line, character, new_name, timeout)

    def type_definition(self, uri: str, line: int, character: int, timeout: float = 15.0) -> list[dict[str, Any]]:
        return self._protocol_ops.type_definition(uri, line, character, timeout)

    def implementation(self, uri: str, line: int, character: int, timeout: float = 15.0) -> list[dict[str, Any]]:
        return self._protocol_ops.implementation(uri, line, character, timeout)

    def call_hierarchy_incoming(self, uri: str, line: int, character: int, timeout: float = 15.0) -> list[dict[str, Any]]:
        return self._protocol_ops.call_hierarchy_incoming(uri, line, character, timeout)

    def call_hierarchy_outgoing(self, uri: str, line: int, character: int, timeout: float = 15.0) -> list[dict[str, Any]]:
        return self._protocol_ops.call_hierarchy_outgoing(uri, line, character, timeout)

    def inlay_hints(self, uri: str, range: dict[str, Any], timeout: float = 15.0) -> list[dict[str, Any]]:
        return self._protocol_ops.inlay_hints(uri, range, timeout)

    def signature_help(self, uri: str, line: int, character: int, trigger_character: str | None = None, timeout: float = 15.0) -> dict[str, Any] | None:
        return self._protocol_ops.signature_help(uri, line, character, trigger_character, timeout)

    def type_hierarchy_supertypes(self, uri: str, line: int, character: int, timeout: float = 15.0) -> list[dict[str, Any]]:
        return self._protocol_ops.type_hierarchy_supertypes(uri, line, character, timeout)

    def type_hierarchy_subtypes(self, uri: str, line: int, character: int, timeout: float = 15.0) -> list[dict[str, Any]]:
        return self._protocol_ops.type_hierarchy_subtypes(uri, line, character, timeout)

    def completion(self, uri: str, line: int, character: int, trigger_character: str | None = None, timeout: float = 15.0) -> list[dict[str, Any]]:
        return self._protocol_ops.completion(uri, line, character, trigger_character, timeout)

    def symbol_context(self, uri: str, line: int, character: int, timeout: float = 15.0) -> dict[str, Any]:
        return self._protocol_ops.symbol_context(uri, line, character, timeout)

    def code_actions(self, uri: str, range: dict[str, Any] | None, only: list[str] | None = None, timeout: float = 15.0) -> list[dict[str, Any]]:
        return self._protocol_ops.code_actions(uri, range, only, timeout)

    def formatting(self, uri: str, options: dict[str, Any] | None = None, timeout: float = 15.0) -> list[dict[str, Any]]:
        return self._protocol_ops.formatting(uri, options, timeout)

    def range_formatting(self, uri: str, range: dict[str, Any], options: dict[str, Any] | None = None, timeout: float = 15.0) -> list[dict[str, Any]]:
        return self._protocol_ops.range_formatting(uri, range, options, timeout)

    def organize_imports(self, uri: str, timeout: float = 15.0) -> dict[str, Any] | None:
        return self._protocol_ops.organize_imports(uri, timeout)

    def apply_edit(self, edit: dict[str, Any], label: str | None = None) -> dict[str, Any]:
        return self._protocol_ops.apply_edit(edit, label)

    def diagnostics(self, min_severity: int = 4, limit: int = 0, timeout: float = 30.0) -> dict[str, list[dict[str, Any]]]:
        return self._diagnostics_handler.diagnostics(min_severity, limit, timeout)

    def file_diagnostics(self, file_path: str | Path, min_severity: int = 4, timeout: float = 5.0) -> list[dict[str, Any]]:
        return self._diagnostics_handler.file_diagnostics(file_path, min_severity, timeout)

    def _on_publish_diagnostics(self, params: dict[str, Any] | None) -> None:
        self._diagnostics_handler._on_publish_diagnostics(params)

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
        if method == "workspace/diagnostic":
            return self._supports_workspace_diagnostic()
        provider_map: dict[str, str] = {
            "textDocument/definition": "definitionProvider",
            "textDocument/hover": "hoverProvider",
            "textDocument/references": "referencesProvider",
            "textDocument/rename": "renameProvider",
            "textDocument/documentSymbol": "documentSymbolProvider",
            "textDocument/typeDefinition": "typeDefinitionProvider",
            "textDocument/implementation": "implementationProvider",
            "textDocument/codeAction": "codeActionProvider",
            "textDocument/formatting": "documentFormattingProvider",
            "textDocument/rangeFormatting": "documentRangeFormattingProvider",
            "textDocument/completion": "completionProvider",
            "textDocument/signatureHelp": "signatureHelpProvider",
            "textDocument/inlayHint": "inlayHintProvider",
            "textDocument/callHierarchy": "callHierarchyProvider",
            "textDocument/typeHierarchy": "typeHierarchyProvider",
            "workspace/symbol": "workspaceSymbolProvider",
        }
        key = provider_map.get(method)
        if key is None:
            return True
        value = self._capabilities.get(key)
        return key in self._capabilities and value is not False and value is not None

    def _supports_workspace_diagnostic(self) -> bool:
        """True if the server advertises LSP 3.17 workspace pull diagnostics."""
        provider = self._capabilities.get("diagnosticProvider")
        if isinstance(provider, dict):
            return bool(provider.get("workspaceDiagnostics"))
        return bool(provider)

    def _batch_cli_name(self) -> str | None:
        return self._diagnostics_handler._batch_cli_name()

    # ── internal ──────────────────────────────────────────────────────────

    # Aliases for backward compatibility with callers that reference these methods
    _path_to_language_id = staticmethod(path_to_language_id)
    _path_to_uri = staticmethod(path_to_uri)
    _canonical_uri = staticmethod(canonical_uri)
    _uri_to_path = staticmethod(uri_to_path)

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
                "diagnostic": {
                    "dynamicRegistration": False,
                    "relatedDocumentSupport": False,
                },
            },
            "workspace": {
                "symbol": {"dynamicRegistration": False},
                "workspaceFolders": True,
                "configuration": True,
                "diagnostics": {
                    "refreshSupport": True,
                },
            },
            "general": {
                "positionEncodings": ["utf-8", "utf-16"],
            },
        }
