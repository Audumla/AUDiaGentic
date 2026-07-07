"""Dependency installation via the workflow step system.

Loads dependency declarations from component YAML files and builds
SequenceStep/SelectStep trees that run through the standard workflow runner.
No separate orchestration lane — deps are workflow steps.
"""
from __future__ import annotations

import logging
import re
import shlex
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from audiagentic.foundation.contracts.errors import make_error_factory
from audiagentic.foundation.io import load_yaml_file
from audiagentic.foundation.toolchains import (
    detect_pkg_manager,
    platform_key,
    tool_available,
    uv_available,
)
from audiagentic.foundation.toolchains.loader import build_step, has_action, raw_step
from audiagentic.foundation.workflow.invocation.steps import (
    SelectStep,
    SequenceStep,
    WorkflowStep,
    planned_commands,
)

from .loader import component_yaml_path

logger = logging.getLogger(__name__)

_dependency_error: Any = make_error_factory("VAL", "DEP", "component-dependencies")


# ---------------------------------------------------------------------------
# Probe resolution
# ---------------------------------------------------------------------------

def _resolve_probe_binary(spec: str) -> Callable[[], bool]:
    binary = spec[7:]
    return lambda: tool_available(binary)


def _resolve_probe_all_binaries(spec: str) -> Callable[[], bool]:
    binaries = tuple(part.strip() for part in spec[13:].split(",") if part.strip())
    return lambda: all(tool_available(binary) for binary in binaries)


def _resolve_probe_path(spec: str) -> Callable[[], bool]:
    p = Path(spec[5:].replace("~", str(Path.home())))
    return lambda: p.exists()


def _resolve_probe_command(spec: str) -> Callable[[], bool]:
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
                encoding="utf-8",
                errors="replace",
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return result.returncode == 0

    return _probe_command


def _resolve_probe_custom(spec: str) -> Callable[[], bool]:
    """Resolve custom: probe spec using colon-separated module:dotpath.

    Delegates to foundation/refs.resolve_ref for consistent
    colon-based resolution across all descriptor types.
    """
    from audiagentic.foundation.refs import resolve_ref

    ref = spec[7:]
    return resolve_ref(ref)


_PROBE_RESOLVERS: dict[str, Callable[[str], Callable[[], bool]]] = {
    "binary:": _resolve_probe_binary,
    "all-binaries:": _resolve_probe_all_binaries,
    "path:": _resolve_probe_path,
    "command:": _resolve_probe_command,
    "custom:": _resolve_probe_custom,
}


def _resolve_probe(spec: str) -> Callable[[], bool]:
    if spec == "toolchain:uv":
        return uv_available

    for prefix, resolver in _PROBE_RESOLVERS.items():
        if spec.startswith(prefix):
            return resolver(spec)

    raise _dependency_error(1, f"unknown probe syntax: {spec!r}", probe=spec)


# ---------------------------------------------------------------------------
# Version constraint checking
# ---------------------------------------------------------------------------

def _parse_version(version_str: str) -> tuple[int, ...] | None:
    """Parse a version string into a tuple of integers for comparison.

    Handles versions like '2.60.0', '1.0', '3.14.159', etc.
    Returns None if the version string cannot be parsed.
    """
    match = re.match(r"^(\d+(?:\.\d+)*)", version_str.strip())
    if not match:
        return None
    return tuple(int(part) for part in match.group(1).split("."))


def _get_tool_version(binary: str) -> tuple[int, ...] | None:
    """Get the installed version of a tool by running <binary> --version.

    Returns None if the tool is not available or version cannot be determined.
    """
    try:
        result = subprocess.run(
            [binary, "--version"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        if result.returncode != 0:
            return None
        output = result.stdout.strip() or result.stderr.strip()
        return _parse_version(output)
    except (OSError, subprocess.TimeoutExpired):
        return None


def check_version_constraint(
    dep_id: str,
    binary: str,
    constraint: str,
) -> str | None:
    """Check if the installed version of a tool satisfies the version constraint.

    Returns None if satisfied, or a warning message if the constraint is not met.
    Supports constraints like '>=2.60.0', '<=3.0.0', '>1.0.0', etc.
    """
    match = re.match(r"^(>=|<=|>|<|==)?\s*(.+)$", constraint.strip())
    if not match:
        logger.warning("Dependency %r: invalid version constraint %r", dep_id, constraint)
        return None

    operator = match.group(1) or ">="
    required_str = match.group(2)
    required = _parse_version(required_str)
    if required is None:
        logger.warning("Dependency %r: cannot parse required version %r", dep_id, required_str)
        return None

    installed = _get_tool_version(binary)
    if installed is None:
        logger.info("Dependency %r: cannot determine version for %r", dep_id, binary)
        return None

    _COMPARE_OPS = {
        ">=": lambda a, b: a < b,
        "<=": lambda a, b: a > b,
        ">": lambda a, b: a <= b,
        "<": lambda a, b: a >= b,
        "==": lambda a, b: a != b,
    }
    if _COMPARE_OPS.get(operator, lambda a, b: False)(installed, required):
        return (
            f"Dependency {dep_id}: installed version "
            f"{'.'.join(map(str, installed))} does not satisfy {constraint}"
        )

    return None


def validate_dependency_versions(dep_cfgs: dict[str, Any]) -> list[str]:
    """Validate version constraints for all dependencies.

    Returns a list of warning messages for dependencies that don't meet their
    version constraints. Empty list if all constraints are satisfied.
    """
    warnings = []
    for dep_id, cfg in dep_cfgs.items():
        version_constraint = cfg.get("version")
        if not version_constraint:
            continue

        # Determine the binary to check
        probe = cfg.get("probe", "")
        if probe.startswith("binary:"):
            binary = probe[7:]
        else:
            # Try to determine binary from dep_id or display-name
            binary = cfg.get("display-name", dep_id).split()[0].lower()

        warning = check_version_constraint(dep_id, binary, version_constraint)
        if warning:
            warnings.append(warning)

    return warnings


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
            pkg, *extra = pkg_spec
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
    return SequenceStep(id=f"{workflow_id}.{action}", steps=cast(tuple[WorkflowStep, ...], steps), fail_fast=False)


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
    targets = names or list(probes.keys())
    return [n for n in targets if n in probes and not probes[n]()]
