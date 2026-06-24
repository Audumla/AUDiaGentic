"""URI/path conversion utilities for LSP sessions.

Provides canonical URI handling, path-to-URI conversion, and language ID
inference from file extensions.
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import quote, unquote, urlparse
from urllib.request import url2pathname

from .lsp_constants import EXTENSION_TO_LANGUAGE


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
    ext = Path(path).suffix.lower().lstrip(".")
    return EXTENSION_TO_LANGUAGE.get(ext, "plaintext")
