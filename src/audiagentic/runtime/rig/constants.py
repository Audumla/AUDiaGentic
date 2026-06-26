"""Shared constants and helpers for the runtime rig modules.

Consolidates platform constants, GitHub release URLs, directory mappings,
and binary name patterns that were previously scattered across
launch.py, binaries.py, process.py, and resolution.py.
"""
from __future__ import annotations

import re
from pathlib import Path

from audiagentic.runtime.system.platform import platform_key

# ---------------------------------------------------------------------------
# Server defaults
# ---------------------------------------------------------------------------

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 42001


# ---------------------------------------------------------------------------
# GitHub release source
# ---------------------------------------------------------------------------

GITHUB_REPO = "ggml-org/llama.cpp"
GITHUB_API = f"https://api.github.com/repos/{GITHUB_REPO}"


# ---------------------------------------------------------------------------
# Platform-to-directory mapping
# ---------------------------------------------------------------------------

PLATFORM_DIR_MAP: dict[str, str] = {
    "win": "windows",
    "darwin": "macOS",
    "linux": "linux",
}


def platform_dir_name() -> str:
    """Return the directory name for the current platform."""
    return PLATFORM_DIR_MAP.get(platform_key(), "linux")


# ---------------------------------------------------------------------------
# Platform-specific binary name patterns (for binaries.py asset matching)
# ---------------------------------------------------------------------------

PLATFORM_PATTERNS: dict[str, tuple[str, re.Pattern, bool, str]] = {
    "win": ("Windows", re.compile(r"^llama-[a-zA-Z0-9]+-bin-win-cpu-x64\.zip$", re.I), True, "llama-server.exe"),
    "darwin": ("macOS", re.compile(r"^llama-[a-zA-Z0-9]+-bin-macos-arm64\.tar\.gz$", re.I), False, "llama-server"),
    "linux": ("Linux", re.compile(r"^llama-[a-zA-Z0-9]+-bin-ubuntu-x64\.tar\.gz$", re.I), False, "llama-server"),
}


# ---------------------------------------------------------------------------
# Platform-specific binary names (for resolution.py find_server_bin)
# ---------------------------------------------------------------------------

def platform_binary_names() -> tuple[str, str]:
    """Return (server_name, fallback_name) for the current platform."""
    if platform_key() == "win":
        return "llama-server.exe", "llamafile.exe"
    return "llama-server", "llamafile"


# ---------------------------------------------------------------------------
# Platform directory resolution helper (replaces resolve_platform_dirs)
# ---------------------------------------------------------------------------

def resolve_platform_dirs(bin_dir: Path) -> tuple[Path, Path]:
    """Resolve server and llamafile directories for the current platform.

    Returns (server_dir, llamafile_dir).
    """
    plat_dir = platform_dir_name()
    server_dir = bin_dir / "llama-server" / plat_dir
    llamafile_dir = bin_dir / "llamafile" / plat_dir
    return server_dir, llamafile_dir
