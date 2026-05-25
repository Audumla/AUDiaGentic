"""Generic system dependency infrastructure using the recipe layer.

Defines the canonical set of system tool dependencies (SYSTEM_DEPENDENCIES)
and provides install/uninstall/detect functions that operate on any
DependencySpec registry. Components import from here and pass their own
subset of dependency IDs.
"""
from __future__ import annotations

import os
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from functools import cache
from pathlib import Path
from typing import Any

from audiagentic.foundation.invoke.base import InvocationRecipe
from audiagentic.foundation.invoke.context import InvocationContext
from audiagentic.foundation.invoke.recipes import PlatformRecipe, ShellRecipe
from audiagentic.foundation.invoke.result import InvocationResult
from audiagentic.foundation.invoke.toolchains import (
    apt,
    brew,
    choco,
    dnf,
    gh_extension,
    pacman,
    scoop,
    winget,
)
from audiagentic.foundation.invoke.toolchains.detect import tool_available
from audiagentic.foundation.output import ComponentOutputEvent, ComponentOutputSink


@dataclass(frozen=True)
class DependencySpec:
    id: str
    check: Callable[[], bool]
    install: InvocationRecipe | None = None
    uninstall: InvocationRecipe | None = None
    requires: tuple[str, ...] = ()
    display_name: str | None = None

    @property
    def label(self) -> str:
        return self.display_name or self.id


@cache
def gh_mcp_available() -> bool:
    """Check whether gh mcp serve is available (extension or built-in).

    Cached per process — gh capability does not change while the process is running.
    Never uses `gh mcp serve` as a probe because it blocks on stdin.
    """
    if not tool_available("gh"):
        return False

    # Fast path: check known extension install directories (cross-platform).
    ext_name = "gh-mcp"
    ext_dirs: list[Path] = [
        Path.home() / ".local" / "share" / "gh" / "extensions" / ext_name,  # Linux
        Path.home() / ".config" / "gh" / "extensions" / ext_name,            # Mac/Linux alt
    ]
    if os.name == "nt":
        for env_var in ("LOCALAPPDATA", "APPDATA"):
            base = os.environ.get(env_var)
            if base:
                ext_dirs.append(Path(base) / "GitHub CLI" / "extensions" / ext_name)
    if any(d.exists() for d in ext_dirs):
        return True

    # Check registered extensions (covers non-standard install locations).
    try:
        r = subprocess.run(["gh", "extension", "list"], capture_output=True, timeout=5, text=True)
        if r.returncode == 0 and ext_name in r.stdout:
            return True
    except (subprocess.TimeoutExpired, OSError):
        return False

    # Check whether gh mcp serve is a built-in (newer gh versions).
    # `gh mcp --help` prints subcommand list and exits — safe to run.
    try:
        r = subprocess.run(["gh", "mcp", "--help"], capture_output=True, timeout=5, text=True)
        return r.returncode == 0 and "serve" in r.stdout
    except (subprocess.TimeoutExpired, OSError):
        return False


def uv_available() -> bool:
    if tool_available("uvx") or tool_available("uv"):
        return True
    local_bin = Path.home() / ".local" / "bin"
    return (local_bin / "uv").exists() or (local_bin / "uvx").exists()


_WINGET_FLAGS = ("--accept-source-agreements", "--accept-package-agreements")
_ASTRAL_UV_INSTALL = ShellRecipe(("sh", "-c", "curl -LsSf https://astral.sh/uv/install.sh | sh"))

SYSTEM_DEPENDENCIES: dict[str, DependencySpec] = {
    "git": DependencySpec(
        id="git",
        check=lambda: tool_available("git"),
        install=PlatformRecipe(
            variants={
                "winget": winget.install("Git.Git", *_WINGET_FLAGS),
                "scoop":  scoop.install("git"),
                "choco":  choco.install("git"),
                "brew":   brew.install("git"),
                "apt":    apt.install("git"),
                "dnf":    dnf.install("git"),
                "pacman": pacman.install("git"),
            },
        ),
        uninstall=PlatformRecipe(
            variants={
                "winget": winget.uninstall("Git.Git"),
                "scoop":  scoop.uninstall("git"),
                "choco":  choco.uninstall("git"),
                "brew":   brew.uninstall("git"),
                "apt":    apt.remove("git"),
                "dnf":    dnf.remove("git"),
                "pacman": pacman.remove("git"),
            },
        ),
    ),
    "gh": DependencySpec(
        id="gh",
        display_name="GitHub CLI",
        check=lambda: tool_available("gh"),
        install=PlatformRecipe(
            variants={
                "winget": winget.install("GitHub.cli", *_WINGET_FLAGS),
                "scoop":  scoop.install("gh"),
                "choco":  choco.install("gh"),
                "brew":   brew.install("gh"),
                "apt":    apt.install("gh"),
                "dnf":    dnf.install("gh"),
                "pacman": pacman.install("github-cli"),
            },
        ),
        uninstall=PlatformRecipe(
            variants={
                "winget": winget.uninstall("GitHub.cli"),
                "scoop":  scoop.uninstall("gh"),
                "choco":  choco.uninstall("gh"),
                "brew":   brew.uninstall("gh"),
                "apt":    apt.remove("gh"),
                "dnf":    dnf.remove("gh"),
                "pacman": pacman.remove("github-cli"),
            },
        ),
    ),
    "uv": DependencySpec(
        id="uv",
        check=uv_available,
        install=PlatformRecipe(
            variants={
                "winget": winget.install("astral-sh.uv", *_WINGET_FLAGS),
                "scoop":  scoop.install("uv"),
                "brew":   brew.install("uv"),
            },
            platform_fallback={"linux": _ASTRAL_UV_INSTALL},
        ),
        uninstall=PlatformRecipe(
            variants={
                "winget": winget.uninstall("astral-sh.uv"),
                "scoop":  scoop.uninstall("uv"),
                "brew":   brew.uninstall("uv"),
            },
        ),
    ),
    "gh-mcp": DependencySpec(
        id="gh-mcp",
        check=gh_mcp_available,
        install=gh_extension.install("shuymn/gh-mcp"),
        uninstall=gh_extension.remove("gh-mcp"),
        requires=("gh",),
    ),
}


def detect_missing(
    deps: Mapping[str, DependencySpec],
    names: list[str] | None = None,
) -> list[str]:
    targets = names if names else list(deps.keys())
    return [n for n in targets if n in deps and not deps[n].check()]


def _context(context: InvocationContext | None, on_progress: ComponentOutputSink | None) -> InvocationContext:
    ctx = context or InvocationContext(on_progress=on_progress)
    if on_progress is not None and ctx.on_progress is not on_progress:
        return replace(ctx, on_progress=on_progress)
    return ctx


def _emit(
    output: ComponentOutputSink | None,
    message: str,
    *,
    progress: float | None = None,
    total: float | None = None,
    **data: Any,
) -> None:
    if output is not None:
        output(ComponentOutputEvent(message=message, progress=progress, total=total, data=data))


def _result_payload(
    spec: DependencySpec,
    result: InvocationResult,
    *,
    verified: bool | None,
    verb: str,
) -> dict[str, Any]:
    error = result.reason if result.status != "ok" else None
    if result.status == "ok" and verified is False:
        error = f"{verb} command succeeded but dependency probe failed"
    return {
        "ok": result.status == "ok" and verified is True,
        "name": spec.id,
        "status": result.status,
        "cmd": result.command,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "error": error,
        "verified": verified,
    }


def _ordered_install_specs(
    deps: Mapping[str, DependencySpec],
    names: list[str],
) -> tuple[list[DependencySpec], list[str]]:
    ordered: list[DependencySpec] = []
    unknown: list[str] = []
    visited: set[str] = set()
    visiting: set[str] = set()

    def visit(name: str) -> None:
        if name in visited:
            return
        spec = deps.get(name)
        if spec is None:
            unknown.append(name)
            return
        if name in visiting:
            raise ValueError(f"circular dependency requirement for '{name}'")
        visiting.add(name)
        for required in spec.requires:
            visit(required)
        visiting.remove(name)
        visited.add(name)
        ordered.append(spec)

    for name in names:
        visit(name)
    return ordered, unknown


def install_dependencies(
    deps: Mapping[str, DependencySpec],
    names: list[str],
    *,
    context: InvocationContext | None = None,
    on_progress: ComponentOutputSink | None = None,
) -> dict[str, Any]:
    ctx = _context(context, on_progress)
    output = on_progress or ctx.on_progress
    specs, unknown = _ordered_install_specs(deps, names)
    results: list[dict[str, Any]] = [
        {"ok": False, "name": name, "error": "unknown dependency"} for name in unknown
    ]
    total = float(len(specs))
    for index, spec in enumerate(specs, start=1):
        _emit(output, f"Checking dependency {spec.label}", progress=float(index - 1), total=total)
        if spec.check():
            results.append({"ok": True, "name": spec.id, "skipped": "already installed"})
            continue
        if spec.install is None:
            results.append({"ok": False, "name": spec.id, "error": "no install recipe defined"})
            continue
        _emit(output, f"Installing dependency {spec.label}", progress=float(index - 1), total=total)
        result = spec.install.run(ctx)
        verified = spec.check() if result.status == "ok" else None
        _emit(output, f"Verified dependency {spec.label}: {verified is True}", progress=float(index), total=total)
        results.append(_result_payload(spec, result, verified=verified, verb="install"))
    return {"results": results}


def uninstall_dependencies(
    deps: Mapping[str, DependencySpec],
    names: list[str],
    *,
    context: InvocationContext | None = None,
    on_progress: ComponentOutputSink | None = None,
) -> dict[str, Any]:
    ctx = _context(context, on_progress)
    output = on_progress or ctx.on_progress
    specs = [deps[name] for name in dict.fromkeys(names) if name in deps]
    unknown = [name for name in dict.fromkeys(names) if name not in deps]
    results: list[dict[str, Any]] = [
        {"ok": False, "name": name, "error": "unknown dependency"} for name in unknown
    ]
    total = float(len(specs))
    for index, spec in enumerate(specs, start=1):
        _emit(output, f"Uninstalling dependency {spec.label}", progress=float(index - 1), total=total)
        if spec.uninstall is None:
            results.append({"ok": False, "name": spec.id, "error": "no uninstall recipe defined"})
            continue
        result = spec.uninstall.run(ctx)
        still_present = spec.check() if result.status == "ok" else None
        verified = not still_present if still_present is not None else None
        _emit(output, f"Verified dependency {spec.label} removed: {verified is True}", progress=float(index), total=total)
        results.append(_result_payload(spec, result, verified=verified, verb="uninstall"))
    return {"results": results}


def install_system_dependencies(
    names: list[str],
    *,
    context: InvocationContext | None = None,
    on_progress: ComponentOutputSink | None = None,
) -> dict[str, Any]:
    return install_dependencies(SYSTEM_DEPENDENCIES, names, context=context, on_progress=on_progress)


def uninstall_system_dependencies(
    names: list[str],
    *,
    context: InvocationContext | None = None,
    on_progress: ComponentOutputSink | None = None,
) -> dict[str, Any]:
    return uninstall_dependencies(SYSTEM_DEPENDENCIES, names, context=context, on_progress=on_progress)
