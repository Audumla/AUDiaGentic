"""Generic system dependency infrastructure.

DependencySpec, _PlatformStep, orchestration (install/uninstall/detect),
and a YAML loader that builds specs from component config declarations.
"""
from __future__ import annotations

import importlib
import os
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

import yaml

from audiagentic.foundation.output import ComponentOutputEvent, ComponentOutputSink
from audiagentic.foundation.toolchains.detect import (
    detect_pkg_manager,
    platform_key,
    tool_available,
)
from audiagentic.foundation.toolchains.loader import build_step, has_action
from audiagentic.foundation.workflow.invocation.models import StepResult
from audiagentic.foundation.workflow.invocation.steps import SequenceStep, ShellStep

_PACKAGE_DIR = Path(__file__).resolve().parents[1]  # audiagentic/
_COMPONENTS_CONFIG_DIR = _PACKAGE_DIR / "config" / "components"


# ---------------------------------------------------------------------------
# Step types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _PlatformStep:
    """Select a step variant based on detected package manager at runtime."""
    variants: dict[str, ShellStep | SequenceStep]
    platform_fallback: dict[str, ShellStep] = field(default_factory=dict)
    detect_fn: Callable[[], str | None] | None = None

    def run(self, context: dict[str, Any]) -> StepResult:
        pm = (self.detect_fn or detect_pkg_manager)()
        if pm and pm in self.variants:
            return self.variants[pm].run(context)
        pk = platform_key()
        if pk in self.platform_fallback:
            return self.platform_fallback[pk].run(context)
        if pm is None:
            reason = f"no supported package manager detected on platform '{pk}'"
        else:
            reason = f"no variant for package manager '{pm}' and no platform fallback for '{pk}'"
        return StepResult(status="failed", reason=reason)


_StepType = ShellStep | SequenceStep | _PlatformStep


# ---------------------------------------------------------------------------
# DependencySpec
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DependencySpec:
    id: str
    check: Callable[[], bool]
    install: _StepType | None = None
    uninstall: _StepType | None = None
    requires: tuple[str, ...] = ()
    display_name: str | None = None

    @property
    def label(self) -> str:
        return self.display_name or self.id


# ---------------------------------------------------------------------------
# Complex probes (too involved for binary: / path: declarations)
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
# YAML loader
# ---------------------------------------------------------------------------

def _find_component_yaml(component_id: str) -> Path:
    for subdir in ("core", "optional"):
        candidate = _COMPONENTS_CONFIG_DIR / subdir / f"{component_id}.yaml"
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"no component config found for '{component_id}'")


def _resolve_check(check_str: str) -> Callable[[], bool]:
    if check_str.startswith("binary:"):
        binary = check_str[7:]
        return lambda: tool_available(binary)
    if check_str.startswith("path:"):
        p = Path(check_str[5:].replace("~", str(Path.home())))
        return lambda: p.exists()
    if check_str.startswith("custom:"):
        dotpath = check_str[7:]
        module_name, fn_name = dotpath.rsplit(".", 1)
        fn = getattr(importlib.import_module(module_name), fn_name)
        return fn
    raise ValueError(f"unknown check syntax: {check_str!r}")


def _uninstall_action(toolchain: str) -> str:
    return "uninstall" if has_action(toolchain, "uninstall") else "remove"


def _build_dep_spec(dep_id: str, cfg: dict[str, Any]) -> DependencySpec:
    check = _resolve_check(cfg["check"])
    requires = tuple(cfg.get("requires", []))
    display_name = cfg.get("display-name")

    if "toolchain" in cfg:
        tc = cfg["toolchain"]
        pkg = cfg["package"]
        uninstall_pkg = cfg.get("uninstall-package", pkg)
        extra = cfg.get("extra-flags", {}).get(tc, [])
        install = build_step(tc, "install", pkg, *extra)
        uninstall = build_step(tc, _uninstall_action(tc), uninstall_pkg)
        return DependencySpec(id=dep_id, check=check, install=install, uninstall=uninstall,
                              requires=requires, display_name=display_name)

    packages: dict[str, str] = cfg.get("packages", {})
    uninstall_packages: dict[str, str] = cfg.get("uninstall-packages", packages)
    extra_flags: dict[str, list[str]] = cfg.get("extra-flags", {})
    platform_fallback_cfg: dict[str, list[str]] = cfg.get("platform-fallback", {})

    install_variants = {
        tc: build_step(tc, "install", pkg, *extra_flags.get(tc, []))
        for tc, pkg in packages.items()
    }
    uninstall_variants = {
        tc: build_step(tc, _uninstall_action(tc), pkg)
        for tc, pkg in uninstall_packages.items()
    }
    platform_fallback = {
        plat: ShellStep(id="install", command=tuple(cmd))
        for plat, cmd in platform_fallback_cfg.items()
    }

    install = _PlatformStep(variants=install_variants, platform_fallback=platform_fallback)
    uninstall = _PlatformStep(variants=uninstall_variants) if uninstall_variants else None
    return DependencySpec(id=dep_id, check=check, install=install, uninstall=uninstall,
                          requires=requires, display_name=display_name)


def load_dependencies(yaml_path: Path) -> dict[str, DependencySpec]:
    """Load DependencySpecs from a component config YAML's dependencies: section."""
    cfg = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    return {
        dep_id: _build_dep_spec(dep_id, dep_cfg)
        for dep_id, dep_cfg in (cfg.get("dependencies") or {}).items()
    }


def load_component_dependencies(component_id: str) -> dict[str, DependencySpec]:
    """Load DependencySpecs for a named component."""
    return load_dependencies(_find_component_yaml(component_id))


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def detect_missing(
    deps: Mapping[str, DependencySpec],
    names: list[str] | None = None,
) -> list[str]:
    targets = names if names else list(deps.keys())
    return [n for n in targets if n in deps and not deps[n].check()]


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
    result: StepResult,
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
        "cmd": result.outputs.get("command"),
        "returncode": result.outputs.get("returncode"),
        "stdout": result.outputs.get("stdout", ""),
        "stderr": result.outputs.get("stderr", ""),
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
    on_progress: ComponentOutputSink | None = None,
) -> dict[str, Any]:
    specs, unknown = _ordered_install_specs(deps, names)
    results: list[dict[str, Any]] = [
        {"ok": False, "name": name, "error": "unknown dependency"} for name in unknown
    ]
    total = float(len(specs))
    for index, spec in enumerate(specs, start=1):
        _emit(on_progress, f"Checking dependency {spec.label}", progress=float(index - 1), total=total)
        if spec.check():
            results.append({"ok": True, "name": spec.id, "skipped": "already installed"})
            continue
        if spec.install is None:
            results.append({"ok": False, "name": spec.id, "error": "no install recipe defined"})
            continue
        _emit(on_progress, f"Installing dependency {spec.label}", progress=float(index - 1), total=total)
        result = spec.install.run({})
        verified = spec.check() if result.status == "ok" else None
        _emit(on_progress, f"Verified dependency {spec.label}: {verified is True}", progress=float(index), total=total)
        results.append(_result_payload(spec, result, verified=verified, verb="install"))
    return {"results": results}


def uninstall_dependencies(
    deps: Mapping[str, DependencySpec],
    names: list[str],
    *,
    on_progress: ComponentOutputSink | None = None,
) -> dict[str, Any]:
    specs = [deps[name] for name in dict.fromkeys(names) if name in deps]
    unknown = [name for name in dict.fromkeys(names) if name not in deps]
    results: list[dict[str, Any]] = [
        {"ok": False, "name": name, "error": "unknown dependency"} for name in unknown
    ]
    total = float(len(specs))
    for index, spec in enumerate(specs, start=1):
        _emit(on_progress, f"Uninstalling dependency {spec.label}", progress=float(index - 1), total=total)
        if spec.uninstall is None:
            results.append({"ok": False, "name": spec.id, "error": "no uninstall recipe defined"})
            continue
        result = spec.uninstall.run({})
        still_present = spec.check() if result.status == "ok" else None
        verified = not still_present if still_present is not None else None
        _emit(on_progress, f"Verified dependency {spec.label} removed: {verified is True}", progress=float(index), total=total)
        results.append(_result_payload(spec, result, verified=verified, verb="uninstall"))
    return {"results": results}
