"""Build, install, switch and roll back the service runtime.

``current`` and ``previous`` are symlinks replaced atomically. A version directory is never
modified after its health check passes, so a rollback is one link swap. Restarting the
gateway is a separate, explicit step (a drop-file the container supervisor watches).
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

Runner = Callable[..., subprocess.CompletedProcess]
DEFAULT_EXTRAS = ("acp", "a2a")
RESTART_FILE = Path("/control/cmd/audiagentic-gateway.restart")
_WHEEL = re.compile(r"^(?P<name>[A-Za-z0-9_.]+)-(?P<version>[0-9][^-]*)-.+\.whl$")
_EXTRA = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


class RuntimeInstallError(RuntimeError):
    """A refused or failed runtime operation; nothing is switched when this is raised."""


def default_root(home: Path) -> Path:
    """The runtime folder sits beside the AUDiaGentic home, outside every checkout."""
    return home.parent / "runtime"


def _run(runner: Runner, command: Sequence[str | Path], **kwargs: Any) -> subprocess.CompletedProcess:
    # The caller's active venv must never steer a build or install into another environment.
    env = {key: value for key, value in os.environ.items() if key not in {"VIRTUAL_ENV", "PYTHONPATH", "PYTHONHOME"}}
    result = runner([str(part) for part in command], capture_output=True, text=True, env=env, **kwargs)
    if result.returncode != 0:
        tail = (result.stderr or result.stdout or "").strip().splitlines()[-3:]
        raise RuntimeInstallError(f"{Path(str(command[0])).name} failed: {' | '.join(tail) or result.returncode}")
    return result


def _link_target(link: Path) -> Path | None:
    try:
        return Path(os.readlink(link))
    except OSError:
        return None


def _set_link(link: Path, target: Path) -> None:
    """Point ``link`` at ``target`` atomically (a reader sees the old or the new, never none)."""
    temporary = link.with_name(f".{link.name}.{os.getpid()}.tmp")
    temporary.unlink(missing_ok=True)
    temporary.symlink_to(target)
    os.replace(temporary, link)


def status(root: Path) -> dict[str, Any]:
    versions = sorted(p.name for p in root.iterdir() if p.is_dir() and not p.is_symlink() and not p.name.startswith(".")) if root.is_dir() else []
    current, previous = _link_target(root / "current"), _link_target(root / "previous")
    return {
        "root": str(root),
        "current": str(current) if current else None,
        "current-healthy": bool(current and (root / "current" / "bin" / "python").exists()),
        "previous": str(previous) if previous else None,
        "versions": versions,
    }


def wheel_from_ref(repo: Path, ref: str, out_dir: Path, *, runner: Runner = subprocess.run) -> Path:
    """Build a wheel of ``ref`` from a clean export (never the working tree)."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,100}", ref):
        raise RuntimeInstallError(f"not a usable ref: {ref!r}")
    uv = shutil.which("uv")
    if uv is None:
        raise RuntimeInstallError("uv is required to build a wheel from a ref")
    with tempfile.TemporaryDirectory(dir=out_dir) as scratch:
        source = Path(scratch) / "src"
        source.mkdir()
        archive = Path(scratch) / "tree.tar"
        _run(runner, ["git", "-C", repo, "archive", "--format=tar", "-o", archive, ref])
        _run(runner, ["tar", "-xf", archive, "-C", source])
        _run(runner, [uv, "build", "--wheel", "--out-dir", out_dir, source])
    wheels = sorted(out_dir.glob("*.whl"), key=lambda p: p.stat().st_mtime)
    if not wheels:
        raise RuntimeInstallError("the build produced no wheel")
    return wheels[-1]


def _health(venv: Path, version: str | None, runner: Runner) -> None:
    """Import the gateway from the venv itself (never an editable or foreign copy)."""
    check = f"assert m.version('audiagentic')=={version!r}, m.version('audiagentic');" if version else ""
    probe = (
        "import importlib.metadata as m, pathlib, sys, audiagentic;"
        "import audiagentic.components.agents.gateway.service.process;"
        + check +
        f"assert pathlib.Path(audiagentic.__file__).resolve().is_relative_to(pathlib.Path({str(venv.resolve())!r})), audiagentic.__file__"
    )
    _run(runner, [venv / "bin" / "python", "-I", "-c", probe])


def install(root: Path, wheel: Path, *, extras: Sequence[str] = DEFAULT_EXTRAS,
            runner: Runner = subprocess.run) -> dict[str, Any]:
    """Install ``wheel`` into a new version folder, health-check it, then make it ``current``."""
    match = _WHEEL.match(wheel.name)
    if not wheel.is_file() or match is None:
        raise RuntimeInstallError(f"not a wheel file: {wheel}")
    if any(not _EXTRA.match(extra) for extra in extras):
        raise RuntimeInstallError("extras must be simple names such as acp,a2a")
    version = match["version"]
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()[:8]
    destination = root / f"{version}-{digest}"
    root.mkdir(parents=True, exist_ok=True)
    uv = shutil.which("uv")
    if uv is None:
        raise RuntimeInstallError("uv is required to install a runtime")
    if not destination.exists():
        try:
            _run(runner, [uv, "venv", "--quiet", destination])
            spec = f"{wheel}[{','.join(extras)}]" if extras else str(wheel)
            _run(runner, [uv, "pip", "install", "--quiet", "--python", destination / "bin" / "python", spec])
            _health(destination, version, runner)
        except RuntimeInstallError:
            shutil.rmtree(destination, ignore_errors=True)  # never leave a half-built version behind
            raise
    else:
        _health(destination, version, runner)
    before = _link_target(root / "current")
    if before is not None and before != Path(destination.name):
        _set_link(root / "previous", before)
    _set_link(root / "current", Path(destination.name))
    return {**status(root), "installed": destination.name, "switched-from": str(before) if before else None}


def rollback(root: Path, *, runner: Runner = subprocess.run) -> dict[str, Any]:
    previous, current = _link_target(root / "previous"), _link_target(root / "current")
    if previous is None or not (root / previous / "bin" / "python").exists():
        raise RuntimeInstallError("there is no previous runtime to return to")
    _health(root / previous, None, runner)
    if current is not None:
        _set_link(root / "previous", current)
    _set_link(root / "current", previous)
    return {**status(root), "rolled-back-to": str(previous)}


def request_gateway_restart(path: Path = RESTART_FILE) -> bool:
    """Ask the supervisor to restart only the gateway; False when no supervisor folder exists."""
    if not path.parent.is_dir():
        return False
    path.touch()
    return True
