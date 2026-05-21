"""Source-control dependency installer.

Manages optional installation of git, gh CLI, gh mcp extension, and uv (uvx) using the
host's native package manager. Detects winget/choco/scoop on Windows, brew on macOS,
and apt/dnf/pacman on Linux. Dependencies are installed only when the user explicitly
requests it via the install_dependencies MCP tool — never automatically on component
install. Uninstall is a separate explicit action and does NOT run on component uninstall.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(frozen=True)
class DependencySpec:
    name: str
    check: Callable[[], bool]
    install_cmds: dict[str, list[str]] = field(default_factory=dict)
    uninstall_cmds: dict[str, list[str]] = field(default_factory=dict)


def _tool_available(name: str) -> bool:
    return shutil.which(name) is not None


def _gh_mcp_available() -> bool:
    if not _tool_available("gh"):
        return False
    result = subprocess.run(["gh", "mcp", "serve", "--help"], capture_output=True)
    return result.returncode == 0


def _detect_pkg_manager() -> str | None:
    if sys.platform.startswith("win"):
        for pm in ("winget", "scoop", "choco"):
            if _tool_available(pm):
                return pm
    elif sys.platform == "darwin":
        if _tool_available("brew"):
            return "brew"
    else:
        for pm in ("apt", "dnf", "pacman"):
            if _tool_available(pm):
                return pm
    return None


DEPENDENCIES: dict[str, DependencySpec] = {
    "git": DependencySpec(
        name="git",
        check=lambda: _tool_available("git"),
        install_cmds={
            "winget": ["winget", "install", "--id", "Git.Git", "-e", "--accept-source-agreements", "--accept-package-agreements"],
            "scoop": ["scoop", "install", "git"],
            "choco": ["choco", "install", "-y", "git"],
            "brew": ["brew", "install", "git"],
            "apt": ["sudo", "apt-get", "install", "-y", "git"],
            "dnf": ["sudo", "dnf", "install", "-y", "git"],
            "pacman": ["sudo", "pacman", "-S", "--noconfirm", "git"],
        },
        uninstall_cmds={
            "winget": ["winget", "uninstall", "--id", "Git.Git", "-e"],
            "scoop": ["scoop", "uninstall", "git"],
            "choco": ["choco", "uninstall", "-y", "git"],
            "brew": ["brew", "uninstall", "git"],
            "apt": ["sudo", "apt-get", "remove", "-y", "git"],
            "dnf": ["sudo", "dnf", "remove", "-y", "git"],
            "pacman": ["sudo", "pacman", "-R", "--noconfirm", "git"],
        },
    ),
    "gh": DependencySpec(
        name="gh",
        check=lambda: _tool_available("gh"),
        install_cmds={
            "winget": ["winget", "install", "--id", "GitHub.cli", "-e", "--accept-source-agreements", "--accept-package-agreements"],
            "scoop": ["scoop", "install", "gh"],
            "choco": ["choco", "install", "-y", "gh"],
            "brew": ["brew", "install", "gh"],
            "apt": ["sudo", "apt-get", "install", "-y", "gh"],
            "dnf": ["sudo", "dnf", "install", "-y", "gh"],
            "pacman": ["sudo", "pacman", "-S", "--noconfirm", "github-cli"],
        },
        uninstall_cmds={
            "winget": ["winget", "uninstall", "--id", "GitHub.cli", "-e"],
            "scoop": ["scoop", "uninstall", "gh"],
            "choco": ["choco", "uninstall", "-y", "gh"],
            "brew": ["brew", "uninstall", "gh"],
            "apt": ["sudo", "apt-get", "remove", "-y", "gh"],
            "dnf": ["sudo", "dnf", "remove", "-y", "gh"],
            "pacman": ["sudo", "pacman", "-R", "--noconfirm", "github-cli"],
        },
    ),
    "uv": DependencySpec(
        name="uv",
        check=lambda: _tool_available("uvx") or _tool_available("uv"),
        install_cmds={
            "winget": ["winget", "install", "--id", "astral-sh.uv", "-e", "--accept-source-agreements", "--accept-package-agreements"],
            "scoop": ["scoop", "install", "uv"],
            "brew": ["brew", "install", "uv"],
            "apt": ["sh", "-c", "curl -LsSf https://astral.sh/uv/install.sh | sh"],
            "dnf": ["sh", "-c", "curl -LsSf https://astral.sh/uv/install.sh | sh"],
            "pacman": ["sh", "-c", "curl -LsSf https://astral.sh/uv/install.sh | sh"],
        },
        uninstall_cmds={
            "winget": ["winget", "uninstall", "--id", "astral-sh.uv", "-e"],
            "scoop": ["scoop", "uninstall", "uv"],
            "brew": ["brew", "uninstall", "uv"],
        },
    ),
    "gh-mcp": DependencySpec(
        name="gh-mcp",
        check=_gh_mcp_available,
        install_cmds={
            # Not package-manager driven — invoked via gh extension regardless of platform.
        },
        uninstall_cmds={},
    ),
}


def _run_install(spec: DependencySpec, pm: str) -> dict[str, Any]:
    cmd = spec.install_cmds.get(pm)
    if not cmd:
        return {"ok": False, "name": spec.name, "error": f"no install recipe for {pm}"}
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        return {
            "ok": result.returncode == 0,
            "name": spec.name,
            "cmd": cmd,
            "returncode": result.returncode,
            "stdout": result.stdout[-2000:],
            "stderr": result.stderr[-2000:],
        }
    except Exception as exc:
        return {"ok": False, "name": spec.name, "cmd": cmd, "error": str(exc)}


def _install_gh_mcp() -> dict[str, Any]:
    if not _tool_available("gh"):
        return {"ok": False, "name": "gh-mcp", "error": "gh not installed — install gh first"}
    cmd = ["gh", "extension", "install", "github/gh-mcp"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        return {
            "ok": result.returncode == 0,
            "name": "gh-mcp",
            "cmd": cmd,
            "returncode": result.returncode,
            "stdout": result.stdout[-2000:],
            "stderr": result.stderr[-2000:],
        }
    except Exception as exc:
        return {"ok": False, "name": "gh-mcp", "cmd": cmd, "error": str(exc)}


def _uninstall_gh_mcp() -> dict[str, Any]:
    if not _tool_available("gh"):
        return {"ok": False, "name": "gh-mcp", "error": "gh not installed"}
    cmd = ["gh", "extension", "remove", "github/gh-mcp"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        return {
            "ok": result.returncode == 0,
            "name": "gh-mcp",
            "cmd": cmd,
            "returncode": result.returncode,
            "stdout": result.stdout[-2000:],
            "stderr": result.stderr[-2000:],
        }
    except Exception as exc:
        return {"ok": False, "name": "gh-mcp", "cmd": cmd, "error": str(exc)}


def detect_missing(names: list[str] | None = None) -> list[str]:
    targets = names if names else list(DEPENDENCIES.keys())
    return [n for n in targets if n in DEPENDENCIES and not DEPENDENCIES[n].check()]


def install_dependencies(names: list[str]) -> dict[str, Any]:
    """Install named dependencies via host package manager. Returns per-item results."""
    pm = _detect_pkg_manager()
    results: list[dict[str, Any]] = []
    for name in names:
        spec = DEPENDENCIES.get(name)
        if spec is None:
            results.append({"ok": False, "name": name, "error": "unknown dependency"})
            continue
        if spec.check():
            results.append({"ok": True, "name": name, "skipped": "already installed"})
            continue
        if name == "gh-mcp":
            results.append(_install_gh_mcp())
            continue
        if pm is None:
            results.append({"ok": False, "name": name, "error": "no supported package manager detected"})
            continue
        results.append(_run_install(spec, pm))
    return {"package-manager": pm, "results": results}


def uninstall_dependencies(names: list[str]) -> dict[str, Any]:
    """Uninstall named dependencies via host package manager. Explicit user action only."""
    pm = _detect_pkg_manager()
    results: list[dict[str, Any]] = []
    for name in names:
        spec = DEPENDENCIES.get(name)
        if spec is None:
            results.append({"ok": False, "name": name, "error": "unknown dependency"})
            continue
        if name == "gh-mcp":
            results.append(_uninstall_gh_mcp())
            continue
        cmd = spec.uninstall_cmds.get(pm) if pm else None
        if not cmd:
            results.append({"ok": False, "name": name, "error": f"no uninstall recipe for {pm}"})
            continue
        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            results.append({
                "ok": result.returncode == 0,
                "name": name,
                "cmd": cmd,
                "returncode": result.returncode,
                "stdout": result.stdout[-2000:],
                "stderr": result.stderr[-2000:],
            })
        except Exception as exc:
            results.append({"ok": False, "name": name, "cmd": cmd, "error": str(exc)})
    return {"package-manager": pm, "results": results}
