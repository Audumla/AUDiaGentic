"""Locate the native Codex binary behind the npm ``codex`` launcher (SH53).

``@openai/codex`` installs ``bin/codex.js``, which runs a native binary from a
per-platform package: ``<package>/vendor/<target>/bin/codex``. The platform
package is found as Node's ``require.resolve`` would, walking ``node_modules``
directories up from the launcher, with the launcher package's own ``vendor``
as the fallback. Qualification evidence must digest that binary, not the
launcher.
"""
from __future__ import annotations

import platform
import sys
from pathlib import Path

# (os, arch) -> (target triple, platform package), as in bin/codex.js.
_TARGETS = {
    ("linux", "x64"): ("x86_64-unknown-linux-musl", "@openai/codex-linux-x64"),
    ("linux", "arm64"): ("aarch64-unknown-linux-musl", "@openai/codex-linux-arm64"),
    ("darwin", "x64"): ("x86_64-apple-darwin", "@openai/codex-darwin-x64"),
    ("darwin", "arm64"): ("aarch64-apple-darwin", "@openai/codex-darwin-arm64"),
    ("win32", "x64"): ("x86_64-pc-windows-msvc", "@openai/codex-win32-x64"),
    ("win32", "arm64"): ("aarch64-pc-windows-msvc", "@openai/codex-win32-arm64"),
}
_ARCH = {"x86_64": "x64", "amd64": "x64", "x64": "x64", "aarch64": "arm64", "arm64": "arm64"}


def locate_native_codex(
    launcher: Path, *, os_name: str | None = None, machine: str | None = None,
) -> Path | None:
    """The native binary ``launcher`` (the resolved ``bin/codex.js``) runs, or None."""
    os_name = os_name or sys.platform
    target = _TARGETS.get((os_name, _ARCH.get((machine or platform.machine()).lower(), "")))
    if target is None or launcher.name != "codex.js" or launcher.parent.name != "bin":
        return None
    triple, package = target
    package_root = launcher.parent.parent
    vendor_roots = [
        directory / "node_modules" / package / "vendor"
        for directory in (package_root, *package_root.parents)
    ]
    vendor_roots.append(package_root / "vendor")
    name = "codex.exe" if os_name == "win32" else "codex"
    for vendor in vendor_roots:
        candidate = vendor / triple / "bin" / name
        if candidate.is_file():
            return candidate.resolve()
    return None
