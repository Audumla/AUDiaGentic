"""Hardcoded constants for the LSP component.

Centralizes method timeouts, severity mappings, symbol kinds, language markers,
client capabilities, and batch-diagnostic CLI mappings so they are defined in
one place and imported where needed.
"""
from __future__ import annotations

from typing import Any

# ── Method→timeout map (performance budgets) ────────────────────────────────

METHOD_TIMEOUTS: dict[str, float] = {
    # File-level queries
    "textDocument/definition": 3.0,
    "textDocument/hover": 3.0,
    "textDocument/references": 3.0,
    "textDocument/typeDefinition": 3.0,
    "textDocument/implementation": 3.0,
    "textDocument/documentSymbol": 3.0,
    "textDocument/codeAction": 3.0,
    "textDocument/formatting": 3.0,
    "textDocument/rangeFormatting": 3.0,
    "textDocument/rename": 3.0,
    "textDocument/completion": 3.0,
    "textDocument/signatureHelp": 3.0,
    "textDocument/inlayHint": 3.0,
    # Workspace-level queries
    "workspace/symbol": 8.0,
    "workspace/diagnostic": 30.0,
    "workspace/configuration": 5.0,
    # Lifecycle
    "initialize": 30.0,
    "shutdown": 5.0,
}

DEFAULT_TIMEOUT: float = 30.0

# ── Symbol kind labels (LSP SymbolKind int → string) ───────────────────────

SYMBOL_KIND_LABELS: dict[int, str] = {
    1: "file", 2: "module", 3: "namespace", 4: "package",
    5: "class", 6: "method", 7: "property", 8: "field",
    9: "constructor", 10: "enum", 11: "interface", 12: "function",
    13: "variable", 14: "constant", 15: "string", 16: "number",
    17: "boolean", 18: "array", 19: "object", 20: "key",
    21: "null", 22: "enum_member", 23: "struct", 24: "event",
    25: "operator", 26: "type_parameter",
}

# ── Completion item kind labels (LSP CompletionItemKind int → string) ──────

COMPLETION_KIND_LABELS: dict[int, str] = {
    1: "text", 2: "method", 3: "function", 4: "constructor",
    5: "field", 6: "variable", 7: "class", 8: "interface",
    9: "unit", 10: "value", 11: "enum", 12: "keyword",
    13: "snippet", 14: "color", 15: "file", 16: "reference",
    17: "folder", 18: "enum_member", 19: "constant", 20: "struct",
    21: "event", 22: "operator", 23: "type_parameter",
}

# ── LSP method → capability label mapping ──────────────────────────────────

METHOD_LABELS: dict[str, str] = {
    "textDocument/definition": "definition",
    "textDocument/hover": "hover",
    "textDocument/references": "references",
    "textDocument/rename": "rename",
    "textDocument/documentSymbol": "documentSymbol",
    "textDocument/typeDefinition": "typeDefinition",
    "textDocument/implementation": "implementation",
    "textDocument/codeAction": "codeAction",
    "textDocument/formatting": "formatting",
    "textDocument/rangeFormatting": "rangeFormatting",
    "textDocument/completion": "completion",
    "textDocument/signatureHelp": "signatureHelp",
    "textDocument/inlayHint": "inlayHint",
    "textDocument/callHierarchy": "callHierarchy",
    "textDocument/typeHierarchy": "typeHierarchy",
    "workspace/symbol": "workspaceSymbol",
    "workspace/diagnostic": "workspaceDiagnostic",
}

# ── Language-specific project markers ──────────────────────────────────────

LANGUAGE_MARKERS: dict[str, list[str]] = {
    "python": ["pyproject.toml", "setup.py", "setup.cfg", "Pipfile", "poetry.lock"],
    "typescript": ["tsconfig.json", "package.json"],
    "javascript": ["package.json"],
    "rust": ["Cargo.toml", "Cargo.lock"],
    "c": ["compile_commands.json", "Makefile", "CMakeLists.txt"],
    "cpp": ["compile_commands.json", "Makefile", "CMakeLists.txt"],
}

# ── File extension → LSP language ID mapping ───────────────────────────────

EXTENSION_TO_LANGUAGE: dict[str, str] = {
    "py": "python", "pyi": "python",
    "ts": "typescript", "tsx": "typescriptreact",
    "js": "javascript", "jsx": "javascriptreact",
    "json": "json", "jsonc": "json",
    "toml": "toml",
    "yaml": "yaml", "yml": "yaml",
    "rs": "rust",
    "c": "c", "h": "c",
    "cpp": "cpp", "cxx": "cpp", "cc": "cpp",
    "hpp": "cpp", "hxx": "cpp", "hh": "cpp",
}

FILE_BASENAME_TO_LANGUAGE: dict[str, str] = {
    "makefile": "make",
    "gnumakefile": "make",
}

# ── pyright --outputjson severity strings → LSP DiagnosticSeverity ints ────

CLI_SEVERITY: dict[str, int] = {"error": 1, "warning": 2, "information": 3}

# ── Batch-diagnostic CLI map (server command → batch-scan CLI) ─────────────

BATCH_DIAGNOSTIC_CLIS: dict[str, str] = {
    "pyright-langserver": "pyright",
    "basedpyright-langserver": "basedpyright",
}

# ── Client capabilities for LSP initialize ─────────────────────────────────

CLIENT_CAPABILITIES: dict[str, Any] = {
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
        "markdown": {
            "supported": True,
        },
    },
}
