"""Protocol operations for LSP sessions.

Extracts request/response method dispatch from LspSession to reduce god-object size.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class LspProtocolOps:
    """Handles LSP request/response operations for a session."""

    def __init__(self, session: Any) -> None:
        self._session = session
        self._position_encoding = session._position_encoding

    @property
    def _bridge(self):
        return self._session.bridge

    def workspace_symbol(self, query: str, timeout: float = 15.0) -> list[dict[str, Any]]:
        """Search for workspace-level symbols matching query."""
        result = self._bridge.send_request(
            "workspace/symbol",
            {"query": query},
            timeout=timeout,
        )
        return _ensure_list(result)

    def document_symbol(self, uri: str, timeout: float = 15.0) -> list[dict[str, Any]]:
        """Get document-level symbols (outline) for a file."""
        result = self._bridge.send_request(
            "textDocument/documentSymbol",
            {"textDocument": {"uri": uri}},
            timeout=timeout,
        )
        return _ensure_list(result)

    def definition(self, uri: str, line: int, character: int, timeout: float = 15.0) -> list[dict[str, Any]]:
        """Go to definition at position."""
        result = self._bridge.send_request(
            "textDocument/definition",
            {
                "textDocument": {"uri": uri},
                "position": self._encode_position(line, character),
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
        result = self._bridge.send_request(
            "textDocument/hover",
            {
                "textDocument": {"uri": uri},
                "position": self._encode_position(line, character),
            },
            timeout=timeout,
        )
        return result

    def references(
        self, uri: str, line: int, character: int, include_declaration: bool = True, timeout: float = 15.0,
    ) -> list[dict[str, Any]]:
        """Find all references to the symbol at position."""
        result = self._bridge.send_request(
            "textDocument/references",
            {
                "textDocument": {"uri": uri},
                "position": self._encode_position(line, character),
                "context": {"includeDeclaration": include_declaration},
            },
            timeout=timeout,
        )
        return _ensure_list(result)

    def rename(
        self, uri: str, line: int, character: int, new_name: str, timeout: float = 30.0,
    ) -> dict[str, Any] | None:
        """Get workspace edit for rename (preview, not applied)."""
        result = self._bridge.send_request(
            "textDocument/rename",
            {
                "textDocument": {"uri": uri},
                "position": self._encode_position(line, character),
                "newName": new_name,
            },
            timeout=timeout,
        )
        return result

    def type_definition(
        self, uri: str, line: int, character: int, timeout: float = 15.0,
    ) -> list[dict[str, Any]]:
        """Go to type definition at position."""
        if not self._session.has_capability("textDocument/typeDefinition"):
            return []
        result = self._bridge.send_request(
            "textDocument/typeDefinition",
            {
                "textDocument": {"uri": uri},
                "position": self._encode_position(line, character),
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
        if not self._session.has_capability("textDocument/implementation"):
            return []
        result = self._bridge.send_request(
            "textDocument/implementation",
            {
                "textDocument": {"uri": uri},
                "position": self._encode_position(line, character),
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
        if not self._session.has_capability("textDocument/callHierarchy"):
            return []
        items = self._bridge.send_request(
            "textDocument/prepareCallHierarchy",
            {
                "textDocument": {"uri": uri},
                "position": self._encode_position(line, character),
            },
            timeout=timeout,
        )
        if not items or not isinstance(items, list):
            return []
        all_calls: list[dict[str, Any]] = []
        for item in items:
            incoming = self._bridge.send_request(
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
        if not self._session.has_capability("textDocument/callHierarchy"):
            return []
        items = self._bridge.send_request(
            "textDocument/prepareCallHierarchy",
            {
                "textDocument": {"uri": uri},
                "position": self._encode_position(line, character),
            },
            timeout=timeout,
        )
        if not items or not isinstance(items, list):
            return []
        all_calls: list[dict[str, Any]] = []
        for item in items:
            outgoing = self._bridge.send_request(
                "callHierarchy/outgoingCalls",
                {"item": item},
                timeout=timeout,
            )
            if isinstance(outgoing, list):
                all_calls.extend(outgoing)
        return all_calls

    def type_hierarchy_supertypes(
        self, uri: str, line: int, character: int, timeout: float = 15.0,
    ) -> list[dict[str, Any]]:
        """Get supertypes for the type at position."""
        if not self._session.has_capability("textDocument/typeHierarchy"):
            return []
        items = self._bridge.send_request(
            "textDocument/prepareTypeHierarchy",
            {
                "textDocument": {"uri": uri},
                "position": self._encode_position(line, character),
            },
            timeout=timeout,
        )
        if not items or not isinstance(items, list):
            return []
        all_types: list[dict[str, Any]] = []
        for item in items:
            supers = self._bridge.send_request(
                "typeHierarchy/supertypes",
                {"item": item},
                timeout=timeout,
            )
            if isinstance(supers, list):
                all_types.extend(supers)
        return all_types

    def type_hierarchy_subtypes(
        self, uri: str, line: int, character: int, timeout: float = 15.0,
    ) -> list[dict[str, Any]]:
        """Get subtypes for the type at position."""
        if not self._session.has_capability("textDocument/typeHierarchy"):
            return []
        items = self._bridge.send_request(
            "textDocument/prepareTypeHierarchy",
            {
                "textDocument": {"uri": uri},
                "position": self._encode_position(line, character),
            },
            timeout=timeout,
        )
        if not items or not isinstance(items, list):
            return []
        all_types: list[dict[str, Any]] = []
        for item in items:
            subs = self._bridge.send_request(
                "typeHierarchy/subtypes",
                {"item": item},
                timeout=timeout,
            )
            if isinstance(subs, list):
                all_types.extend(subs)
        return all_types

    def code_actions(
        self, uri: str, range: dict[str, Any] | None, only: list[str] | None = None,
        timeout: float = 15.0,
    ) -> list[dict[str, Any]]:
        """Get code actions (quick fixes, refactors) for a range."""
        if not self._session.has_capability("textDocument/codeAction"):
            return []
        params: dict[str, Any] = {
            "textDocument": {"uri": uri},
            "range": range or {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 0}},
            "context": {"diagnostics": [], "only": only or []},
        }
        result = self._bridge.send_request("textDocument/codeAction", params, timeout=timeout)
        return _ensure_list(result)

    def formatting(
        self, uri: str, options: dict[str, Any] | None = None, timeout: float = 15.0,
    ) -> list[dict[str, Any]]:
        """Get document formatting edits."""
        if not self._session.has_capability("textDocument/formatting"):
            return []
        params: dict[str, Any] = {
            "textDocument": {"uri": uri},
            "options": options or {"tabSize": 4, "insertSpaces": True},
        }
        result = self._bridge.send_request("textDocument/formatting", params, timeout=timeout)
        return _ensure_list(result)

    def range_formatting(
        self, uri: str, range: dict[str, Any], options: dict[str, Any] | None = None,
        timeout: float = 15.0,
    ) -> list[dict[str, Any]]:
        """Get range formatting edits."""
        if not self._session.has_capability("textDocument/rangeFormatting"):
            return []
        params: dict[str, Any] = {
            "textDocument": {"uri": uri},
            "range": range,
            "options": options or {"tabSize": 4, "insertSpaces": True},
        }
        result = self._bridge.send_request("textDocument/rangeFormatting", params, timeout=timeout)
        return _ensure_list(result)

    def organize_imports(
        self, uri: str, timeout: float = 15.0,
    ) -> dict[str, Any] | None:
        """Get organize imports workspace edit."""
        if not self._session.has_capability("textDocument/codeAction"):
            return None
        actions = self.code_actions(uri, None, only=["source.organizeImports"], timeout=timeout)
        for action in actions:
            if isinstance(action, dict) and action.get("edit"):
                return action.get("edit")
        return None

    def apply_edit(
        self, edit: dict[str, Any], label: str | None = None,
    ) -> dict[str, Any]:
        """Apply a workspace edit via workspace/applyEdit request."""
        params: dict[str, Any] = {"edit": edit}
        if label:
            params["label"] = label
        result = self._bridge.send_request("workspace/applyEdit", params)
        return result or {}

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

    def _encode_position(self, line: int, character: int) -> dict[str, int]:
        """Encode a position for LSP transmission."""
        if self._position_encoding == "utf-8":
            return {"line": line, "character": character}
        # UTF-16: count code units (surrogate pairs = 2 units each)
        return {"line": line, "character": character}  # Simplified - full encoding in lsp_lifecycle


def _ensure_list(result: Any) -> list[dict[str, Any]]:
    """Return result if it's a list, else empty list."""
    return result if isinstance(result, list) else []
