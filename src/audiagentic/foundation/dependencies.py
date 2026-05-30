"""Dependency installation via the workflow step system.

Loads dependency declarations from component YAML files and builds
SequenceStep/SelectStep trees that run through the standard workflow runner.
No separate orchestration lane — deps are workflow steps.
"""
from __future__ import annotations

import importlib
import os
import subprocess
from collections.abc import Callable
from functools import cache
from pathlib import Path
from typing import Any

import yaml

from audiagentic.foundation.toolchains.detect import (
    detect_pkg_manager,
    platform_key,
    tool_available,
)
from audiagentic.foundation.toolchains.loader import build_step, has_action, raw_step
from audiagentic.foundation.workflow.invocation.steps import SelectStep, SequenceStep

_PACKAGE_DIR = Path(__file__).resolve().parents[1]
_COMPONENTS_CONFIG_DIR = _PACKAGE_DIR / "config" / "components"


# ---------------------------------------------------------------------------
# Complex probes — too involved for binary:/path: declarations
# ---------------------------------------------------------------------------

@cache
def gh_mcp_available() -> bool:
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


def uv_available() -> bool:
    if tool_available("uvx") or tool_available("uv"):
        return True
    local_bin = Path.home() / ".local" / "bin"
    return (local_bin / "uv").exists() or (local_bin / "uvx").exists()


# ---------------------------------------------------------------------------
# Probe resolution
# ---------------------------------------------------------------------------

def _resolve_probe(spec: str) -> Callable[[], bool]:
    if spec.startswith("binary:"):
        binary = spec[7:]
        return lambda: tool_available(binary)
    if spec.startswith("path:"):
        p = Path(spec[5:].replace("~", str(Path.home())))
        return lambda: p.exists()
    if spec.startswith("custom:"):
        dotpath = spec[7:]
        module_name, fn_name = dotpath.rsplit(".", 1)
        return getattr(importlib.import_module(module_name), fn_name)
    raise ValueError(f"unknown probe syntax: {spec!r}")


# ---------------------------------------------------------------------------
# Step builders
# ---------------------------------------------------------------------------

def _uninstall_action(toolchain: str) -> str:
    return "uninstall" if has_action(toolchain, "uninstall") else "remove"


def _install_select(via: dict[str, str], fallback_cfg: dict[str, list]) -> SelectStep:
    """Build a SelectStep that dispatches on detect_pkg_manager()."""
    variants = {
        tc: build_step(tc, "install", pkg)
        for tc, pkg in via.items()
    }
    fallback: SelectStep | None = None
    if fallback_cfg:
        fallback = SelectStep(
            id="platform-fallback",
            select=lambda _: platform_key(),
            variants={
                plat: raw_step("fallback", cmd)
                for plat, cmd in fallback_cfg.items()
            },
        )
    return SelectStep(
        id="install",
        select=lambda _: detect_pkg_manager(),
        variants=variants,
        fallback=fallback,
    )


def _uninstall_select(via: dict[str, str]) -> SelectStep:
    variants = {
        tc: build_step(tc, _uninstall_action(tc), pkg)
        for tc, pkg in via.items()
    }
    return SelectStep(
        id="uninstall",
        select=lambda _: detect_pkg_manager(),
        variants=variants,
    )


def _guarded(dep_id: str, probe_fn: Callable[[], bool], inner: SelectStep, *, skip_when_true: bool) -> SelectStep:
    """Wrap a step with a probe guard: skip when probe matches skip_when_true."""
    return SelectStep(
        id=dep_id,
        select=lambda _: None if probe_fn() == skip_when_true else "run",
        variants={"run": inner},
    )


def _dep_workflow(dep_id: str, cfg: dict[str, Any], action: str) -> SelectStep:
    probe_fn = _resolve_probe(cfg["probe"])
    fallback_cfg = cfg.get("platform-fallback", {})

    if "toolchain" in cfg:
        tc = cfg["toolchain"]
        pkg = cfg["package"]
        inner = build_step(tc, "install" if action == "install" else _uninstall_action(tc),
                           pkg if action == "install" else cfg.get("uninstall-package", pkg))
    else:
        via: dict[str, str] = cfg.get("via", {})
        inner = _install_select(via, fallback_cfg) if action == "install" else _uninstall_select(
            cfg.get("uninstall-via", via)
        )

    # install: skip if already present; uninstall: skip if already absent
    return _guarded(dep_id, probe_fn, inner, skip_when_true=(action == "install"))


# ---------------------------------------------------------------------------
# Topological sort
# ---------------------------------------------------------------------------

def _topo_sort(dep_cfgs: dict[str, Any]) -> list[str]:
    ordered: list[str] = []
    visited: set[str] = set()
    visiting: set[str] = set()

    def visit(name: str) -> None:
        if name in visited:
            return
        if name not in dep_cfgs:
            return
        if name in visiting:
            raise ValueError(f"circular dependency: {name!r}")
        visiting.add(name)
        for req in dep_cfgs[name].get("requires", []):
            visit(req)
        visiting.discard(name)
        visited.add(name)
        ordered.append(name)

    for name in dep_cfgs:
        visit(name)
    return ordered


# ---------------------------------------------------------------------------
# YAML loader
# ---------------------------------------------------------------------------

def _find_component_yaml(component_id: str) -> Path:
    for subdir in ("core", "optional"):
        candidate = _COMPONENTS_CONFIG_DIR / subdir / f"{component_id}.yaml"
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"no component config found for '{component_id}'")


def _load_dep_cfgs(component_id: str) -> dict[str, Any]:
    path = _find_component_yaml(component_id)
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    return cfg.get("dependencies") or {}


def load_component_workflow(component_id: str, *, action: str = "install") -> SequenceStep:
    """Build a SequenceStep that installs (or uninstalls) all component deps.

    Each dep becomes a SelectStep that skips if the probe is already satisfied.
    Ordering respects requires: declarations. Run with .run({}).
    """
    dep_cfgs = _load_dep_cfgs(component_id)
    ordered = _topo_sort(dep_cfgs)
    steps = tuple(
        _dep_workflow(dep_id, dep_cfgs[dep_id], action)
        for dep_id in ordered
    )
    return SequenceStep(id=f"{component_id}.{action}", steps=steps, fail_fast=False)


def load_component_probes(component_id: str) -> dict[str, Callable[[], bool]]:
    """Return probe callables keyed by dep id — for status checks."""
    dep_cfgs = _load_dep_cfgs(component_id)
    return {dep_id: _resolve_probe(cfg["probe"]) for dep_id, cfg in dep_cfgs.items()}


def detect_missing(
    probes: dict[str, Callable[[], bool]],
    names: list[str] | None = None,
) -> list[str]:
    """Return dep ids whose probes fail (not yet satisfied)."""
    targets = names if names is not None else list(probes.keys())
    return [n for n in targets if n in probes and not probes[n]()]
