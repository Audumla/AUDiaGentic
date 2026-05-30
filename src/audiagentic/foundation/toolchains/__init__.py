from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from audiagentic.foundation.workflow.invocation.steps import SequenceStep, ShellStep

from .loader import _toolchains, build_step


def _make_action(name: str, action: str):
    def _fn(package: str, *extra: str) -> ShellStep | SequenceStep:
        return build_step(name, action, package, *extra)

    return _fn


def _make_tc(name: str, tc: dict[str, Any]) -> SimpleNamespace:
    ns: dict[str, Any] = {}
    for key in tc:
        if key in ("privilege", "install_steps"):
            continue
        ns[key] = _make_action(name, key)
    if "install_steps" in tc:
        ns.setdefault("install", _make_action(name, "install"))
    return SimpleNamespace(**ns)


def _uv_install(package: str, *pre_flags: str) -> ShellStep:
    template = _toolchains()["uv"]["install"]
    idx = template.index("{package}")
    cmd = tuple(template[:idx]) + pre_flags + (package,) + tuple(template[idx + 1:])
    return ShellStep(id="install", command=cmd)


_tcs = {name: _make_tc(name, tc) for name, tc in _toolchains().items()}
_tcs["uv"].install = _uv_install

apt = _tcs["apt"]
brew = _tcs["brew"]
cargo = _tcs["cargo"]
choco = _tcs["choco"]
dnf = _tcs["dnf"]
gh_extension = _tcs["gh_extension"]
npm = _tcs["npm"]
pacman = _tcs["pacman"]
scoop = _tcs["scoop"]
uv = _tcs["uv"]
vscode = _tcs["vscode"]
winget = _tcs["winget"]

__all__ = ["apt", "brew", "cargo", "choco", "dnf", "gh_extension", "npm", "pacman", "scoop", "uv", "vscode", "winget"]
