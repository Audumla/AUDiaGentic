"""Source-control-specific dependency probes.

Loaded via the ``custom:`` probe seam in source-control.yaml. These live with
the component that owns the tool (GitHub CLI), keeping foundation toolchain
detection tool-agnostic.
"""
from __future__ import annotations

import os
import subprocess
from functools import cache
from pathlib import Path

from audiagentic.foundation.toolchains.detect import tool_available


@cache
def gh_mcp_available() -> bool:
    """Return True if the GitHub CLI ``gh-mcp`` extension is installed."""
    if not tool_available("gh"):
        return False
    ext_name = "gh-mcp"
    ext_dirs: list[Path] = [
        Path.home() / ".local" / "share" / "gh" / "extensions" / ext_name,
        Path.home() / ".config" / "gh" / "extensions" / ext_name,
    ]
    if os.name == "nt":
        for env_var in ("LOCALAPPDATA", "APPDATA"):
            base = os.environ.get(env_var)
            if base:
                ext_dirs.append(Path(base) / "GitHub CLI" / "extensions" / ext_name)
    if any(d.exists() for d in ext_dirs):
        return True
    try:
        r = subprocess.run(["gh", "extension", "list"], capture_output=True, timeout=5, text=True)
        if r.returncode == 0 and ext_name in r.stdout:
            return True
    except (subprocess.TimeoutExpired, OSError):
        return False
    try:
        r = subprocess.run(["gh", "mcp", "--help"], capture_output=True, timeout=5, text=True)
        return r.returncode == 0 and "serve" in r.stdout
    except (subprocess.TimeoutExpired, OSError):
        return False
