from __future__ import annotations

from functools import cache
from pathlib import Path
from typing import Any

import yaml

from audiagentic.foundation.workflow.invocation.steps import SequenceStep, ShellStep

from .detect import privilege_prefix

_YAML_PATH = Path(__file__).parent / "toolchains.yaml"


@cache
def _toolchains() -> dict[str, Any]:
    return yaml.safe_load(_YAML_PATH.read_text(encoding="utf-8"))["toolchains"]


def _expand(template: list[str], package: str, priv: bool) -> tuple[str, ...]:
    prefix = privilege_prefix() if priv else ()
    return (*prefix, *(s.replace("{package}", package) for s in template))


def raw_step(step_id: str, command: list[str]) -> ShellStep:
    """Wrap a raw command list as a ShellStep without a toolchain lookup."""
    return ShellStep(id=step_id, command=tuple(command))


def has_action(toolchain: str, action: str) -> bool:
    tc = _toolchains()[toolchain]
    if action == "install":
        return "install" in tc or "install_steps" in tc
    return action in tc


def build_step(toolchain: str, action: str, package: str, *extra: str) -> ShellStep | SequenceStep:
    tc = _toolchains()[toolchain]
    priv = tc.get("privilege", False)
    if action == "install" and "install_steps" in tc:
        steps = tuple(
            ShellStep(id=f"step_{i}", command=_expand(s, package, priv))
            for i, s in enumerate(tc["install_steps"])
        )
        return SequenceStep(id="install", steps=steps)
    cmd = _expand(tc[action], package, priv) + extra
    return ShellStep(id=action, command=cmd)
