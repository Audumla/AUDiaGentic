"""Normalized host target facts shared by provider capability services."""
from __future__ import annotations

import platform
import sys


def detect_platform_triple() -> str:
    """Return the current host as ``windows|darwin|linux`` plus architecture."""
    if sys.platform.startswith("win"):
        os_name = "windows"
    elif sys.platform == "darwin":
        os_name = "darwin"
    else:
        os_name = "linux"

    raw_arch = platform.machine().lower()
    arch = {
        "amd64": "amd64",
        "x86_64": "amd64",
        "arm64": "arm64",
        "aarch64": "arm64",
        "x86": "386",
    }.get(raw_arch, raw_arch)
    return f"{os_name}-{arch}"


__all__ = ["detect_platform_triple"]
