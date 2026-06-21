"""Dependency installation via the workflow step system.

Loads dependency declarations from component YAML files and builds
SequenceStep/SelectStep trees that run through the standard workflow runner.
No separate orchestration lane — deps are workflow steps.
"""
from __future__ import annotations

import shlex
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from audiagentic.foundation.contracts.errors import AudiaGenticError, make_error
from audiagentic.foundation.io import load_yaml_file
from audiagentic.foundation.toolchains.detect import (
    detect_pkg_manager,
    platform_key,
    tool_available,
    uv_available,
)
from audiagentic.foundation.toolchains.loader import build_step, has_action, raw_step
from audiagentic.foundation.workflow.invocation.steps import (
    SelectStep,
    SequenceStep,
    planned_commands,
)

from .loader import component_yaml_path


def _dependency_error(code_number: int, message: str, **details: object) -> AudiaGenticError:
    return make_error(
        prefix="VAL",
        component="DEP",
        number=code_number,
        kind="component-dependencies",
        message=message,
        details=details,
    )


# ---------------------------------------------------------------------------
# Probe resolution
# ---------------------------------------------------------------------------

def _resolve_probe(spec: str) -> Callable[[], bool]:
    if spec.startswith("binary:"):
        binary = spec[7:]
        return lambda: tool_available(binary)
    if spec.startswith("all-binaries:"):
        binaries = tuple(part.strip() for part in spec[13:].split(",") if part.strip())
        return lambda: all(tool_available(binary) for binary in binaries)
    if spec.startswith("path:"):
        p = Path(spec[5:].replace("~", str(Path.home())))
        return lambda: p.exists()
    if spec == "toolchain:uv":
        return uv_available
    if spec.startswith("command:"):
        command = tuple(shlex.split(spec[8:]))

        def _probe_command() -> bool:
            if not command:
                return False
            try:
                result = subprocess.run(
                    command,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
            except (OSError, subprocess.TimeoutExpired):
                return False
            return result.returncode == 0

        return _probe_command
    if spec.startswith("custom:"):
        dotpath = spec[7:]
        import importlib
        module_name, fn_name = dotpath.rsplit(".", 1)
        return getattr(importlib.import_module(module_name), fn_name)
    raise _dependency_error(1, f"unknown probe syntax: {spec!r}", probe=spec)


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


def _guarded(dep_id: str, probe_fn: Callable[[], bool], inner: Any, *, skip_when_true: bool) -> SelectStep:
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
        pkg_spec = cfg["package"] if action == "install" else cfg.get("uninstall-package", cfg["package"])
        if isinstance(pkg_spec, list):
            if not pkg_spec:
                raise _dependency_error(2, f"{dep_id}: package list must not be empty", dependency=dep_id)
            pkg = pkg_spec[0]
            extra = tuple(pkg_spec[1:])
        else:
            pkg = pkg_spec
            extra = ()
        inner = build_step(tc, "install" if action == "install" else _uninstall_action(tc), pkg, *extra)
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
            raise _dependency_error(3, f"circular dependency: {name!r}", dependency=name)
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

def _load_dep_cfgs(component_id: str) -> dict[str, Any]:
    cfg = load_yaml_file(component_yaml_path(component_id))
    return cfg.get("dependencies") or {}


# ---------------------------------------------------------------------------
# Builders over explicit dep-cfg dicts
#
# These accept dependency configs directly so callers that source deps from
# somewhere other than a component YAML `dependencies:` block (e.g. the
# coding-lsp per-language registry) reuse the same workflow machinery.
# ---------------------------------------------------------------------------

def build_dependency_workflow(
    dep_cfgs: dict[str, Any], *, workflow_id: str, action: str = "install"
) -> SequenceStep:
    """Build a SequenceStep that installs (or uninstalls) the given deps.

    Each dep becomes a SelectStep that skips if the probe is already satisfied.
    Ordering respects requires: declarations. Run with .run({}).
    """
    ordered = _topo_sort(dep_cfgs)
    steps = tuple(
        _dep_workflow(dep_id, dep_cfgs[dep_id], action)
        for dep_id in ordered
    )
    return SequenceStep(id=f"{workflow_id}.{action}", steps=steps, fail_fast=False)


def build_dependency_probes(dep_cfgs: dict[str, Any]) -> dict[str, Callable[[], bool]]:
    return {dep_id: _resolve_probe(cfg["probe"]) for dep_id, cfg in dep_cfgs.items()}


def build_dependency_labels(dep_cfgs: dict[str, Any]) -> dict[str, str]:
    return {dep_id: cfg.get("display-name", dep_id) for dep_id, cfg in dep_cfgs.items()}


def build_dependency_install_commands(
    dep_cfgs: dict[str, Any],
    names: list[str] | None = None,
    *,
    workflow_id: str = "deps",
) -> dict[str, list[list[str]]]:
    workflow = build_dependency_workflow(dep_cfgs, workflow_id=workflow_id, action="install")
    targets = set(names) if names is not None else None
    return {
        step.id: planned_commands(step)
        for step in workflow.steps
        if targets is None or step.id in targets
    }


# ---------------------------------------------------------------------------
# Component-id convenience wrappers (source deps from component YAML)
# ---------------------------------------------------------------------------

def load_dependency_workflow(component_id: str, *, action: str = "install") -> SequenceStep:
    """Build a dependency workflow from a component's YAML `dependencies:` block."""
    return build_dependency_workflow(
        _load_dep_cfgs(component_id), workflow_id=component_id, action=action
    )


def load_dependency_probes(component_id: str) -> dict[str, Callable[[], bool]]:
    """Return probe callables keyed by dep id — for status checks."""
    return build_dependency_probes(_load_dep_cfgs(component_id))


def load_dependency_labels(component_id: str) -> dict[str, str]:
    """Return human-readable display labels keyed by dep id (falls back to id)."""
    return build_dependency_labels(_load_dep_cfgs(component_id))


def load_dependency_install_commands(
    component_id: str,
    names: list[str] | None = None,
) -> dict[str, list[list[str]]]:
    """Return planned install commands for component dependencies.

    Commands are derived from the same dependency workflow used by installers,
    so status messages stay in sync with component YAML declarations.
    """
    return build_dependency_install_commands(
        _load_dep_cfgs(component_id), names, workflow_id=component_id
    )


def detect_missing(
    probes: dict[str, Callable[[], bool]],
    names: list[str] | None = None,
) -> list[str]:
    """Return dep ids whose probes fail (not yet satisfied)."""
    targets = names if names is not None else list(probes.keys())
    return [n for n in targets if n in probes and not probes[n]()]
