"""Hardcoded constants for the LSP component.

Centralizes method timeouts, severity mappings, symbol kinds, language markers,
client capabilities, and batch-diagnostic CLI mappings so they are defined in
one place and imported where needed.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.foundation.io import load_yaml_file

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
    # Document diagnostics — needs higher budget for large files with deep imports
    "textDocument/diagnostic": 60.0,
    # Workspace-level queries
    "workspace/symbol": 8.0,
    "workspace/diagnostic": 30.0,
    "workspace/configuration": 5.0,
    # Lifecycle
    "initialize": 30.0,
    "shutdown": 5.0,
}

DEFAULT_TIMEOUT: float = 30.0

# ── Config-driven label maps (loaded from coding-lsp.yaml) ─────────────

_Coding_LSP_YAML = Path(__file__).resolve().parents[2] / "config" / "components" / "coding-lsp.yaml"


def _load_label_maps() -> dict[str, Any]:
    """Load user-facing label maps from the LSP component YAML config."""
    cfg = load_yaml_file(_Coding_LSP_YAML)
    return cfg.get("label-maps", {})


_LABEL_MAPS = _load_label_maps()

# ── Symbol kind labels (LSP SymbolKind int → string) ───────────────────────

SYMBOL_KIND_LABELS: dict[int, str] = _LABEL_MAPS.get("symbol-kind-labels", {})

# ── Completion item kind labels (LSP CompletionItemKind int → string) ──────

COMPLETION_KIND_LABELS: dict[int, str] = _LABEL_MAPS.get("completion-kind-labels", {})

# ── LSP method → capability label mapping ──────────────────────────────────

METHOD_LABELS: dict[str, str] = _LABEL_MAPS.get("method-labels", {})

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

EXTENSION_TO_LANGUAGE: dict[str, str] = _LABEL_MAPS.get("extension-to-language", {})
FILE_BASENAME_TO_LANGUAGE: dict[str, str] = _LABEL_MAPS.get("file-basename-to-language", {})

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
