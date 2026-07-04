"""URI/path/position utilities and LSP result normalization.

Provides canonical URI handling, path-to-URI conversion, language ID
inference, position parsing, and the normalize_* helpers that map raw LSP
payloads to the consistent schemas the MCP surface returns.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlparse
from urllib.request import url2pathname

from .lsp_constants import (
    EXTENSION_TO_LANGUAGE,
    FILE_BASENAME_TO_LANGUAGE,
    SYMBOL_KIND_LABELS,
)


def path_to_uri(path: Path) -> str:
    """Convert a filesystem path to a file:// URI."""
    return path.as_uri()


def uri_to_path(uri: str) -> Path:
    """Convert a file:// URI to a filesystem path.

    Uses url2pathname (works on 3.12); Path.from_uri is 3.13+ only and the
    runtime here is 3.12, where it raises AttributeError.
    """
    if uri.startswith("file://"):
        parsed = urlparse(uri)
        return Path(url2pathname(unquote(parsed.path)))
    return Path(uri)


def canonical_uri(uri: str) -> str:
    """Canonicalize a file URI for stable keying across client/server variants.

    Client URIs come from ``Path.resolve().as_uri()`` (uppercase Windows drive,
    ``urllib``-style percent-encoding). Servers (pyright, pylsp, …) frequently
    publish the same file with a lowercase drive letter and/or different
    percent-encoding. Keying state dicts on raw strings then misses, so
    publishDiagnostics never matches the lookup and the tool silently returns
    no diagnostics. Normalize to one form: decode, uppercase the drive, re-quote.
    Pure string work — no filesystem I/O (safe in the notification handler).
    """
    if not uri.startswith("file://"):
        return uri
    rest = unquote(uri[len("file://"):])
    # "/h:/..." -> "/H:/..." (Windows drive letter)
    if len(rest) >= 3 and rest[0] == "/" and rest[2] == ":":
        rest = "/" + rest[1].upper() + rest[2:]
    return "file://" + quote(rest, safe="/:@")


def path_to_language_id(path: str) -> str:
    """Infer LSP language ID from file extension."""
    p = Path(path)
    ext = p.suffix.lower().lstrip(".")
    if ext:
        return EXTENSION_TO_LANGUAGE.get(ext, "plaintext")
    return FILE_BASENAME_TO_LANGUAGE.get(p.name.lower(), "plaintext")


def parse_position(pos: str) -> tuple[int, int]:
    """Parse 'line:column' string to 0-based (line, character)."""
    parts = pos.split(":")
    line = int(parts[0]) - 1
    character = int(parts[1]) - 1 if len(parts) > 1 else 0
    return line, character


def file_to_uri(file_path: str | Path) -> str:
    """Convert file path to file:// URI."""
    return Path(file_path).resolve().as_uri()


def uri_to_repo_relative(uri: str, project_root: Path) -> str:
    """Convert a file:// URI to a repo-relative path string."""
    path = uri_to_path(uri)
    try:
        return str(path.relative_to(project_root))
    except ValueError:
        return str(path)


def normalize_location(loc: dict[str, Any], project_root: Path) -> dict[str, Any]:
    """Normalize an LSP Location to consistent schema."""
    return {
        "file": uri_to_repo_relative(loc.get("uri", ""), project_root),
        "uri": loc.get("uri", ""),
        "range": loc.get("range", {}),
        "line": loc.get("range", {}).get("start", {}).get("line", 0),
        "character": loc.get("range", {}).get("start", {}).get("character", 0),
    }


def normalize_symbol(sym: dict[str, Any], project_root: Path) -> dict[str, Any]:
    """Normalize an LSP SymbolInformation or DocumentSymbol to consistent schema."""
    loc = sym.get("location", {})
    return {
        "name": sym.get("name", ""),
        "kind": SYMBOL_KIND_LABELS.get(sym.get("kind", 0), f"unknown({sym.get('kind', '?')})"),
        "kind_raw": sym.get("kind", 0),
        "file": uri_to_repo_relative(loc.get("uri", ""), project_root),
        "uri": loc.get("uri", ""),
        "range": loc.get("range", sym.get("range", {})),
        "container_name": sym.get("containerName", ""),
        "children": [normalize_symbol(c, project_root) for c in sym.get("children", [])] if "children" in sym else [],
    }


def normalize_hover(hover: dict[str, Any] | None) -> dict[str, Any] | None:
    """Normalize an LSP Hover response to consistent schema."""
    if not hover:
        return None
    contents = hover.get("contents", {})
    if isinstance(contents, dict):
        value = contents.get("value", "")
        kind = contents.get("kind", "plaintext")
    elif isinstance(contents, list):
        first = next((c for c in contents if isinstance(c, dict)), {})
        value = first.get("value", str(contents))
        kind = first.get("kind", "plaintext")
    else:
        value = str(contents)
        kind = "plaintext"
    return {
        "contents": value,
        "format": kind,
        "range": hover.get("range", {}),
    }


def normalize_workspace_edit(edit: dict[str, Any] | None, project_root: Path) -> dict[str, Any] | None:
    """Normalize an LSP WorkspaceEdit to consistent schema."""
    if not edit:
        return None
    changes = edit.get("changes", {})
    normalized_changes: dict[str, list[dict[str, Any]]] = {}
    for uri, ops in changes.items():
        normalized_changes[uri_to_repo_relative(uri, project_root)] = ops
    return {
        "document_changes": edit.get("documentChanges", []),
        "changes": normalized_changes,
        "change_annotations": edit.get("changeAnnotations", {}),
    }
