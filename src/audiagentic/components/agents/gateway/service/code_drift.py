"""Has the code on disk changed since the gateway service started? (read-only)

The gateway service imports its code once. When the shared runtime is then moved to
other commits without a restart, new processes run the new code against a service
still running the old one, and requests fail in ways that look like unrelated bugs.
For a git checkout it compares the commit that was checked out when the service
started (from the reflog) with the commit checked out now, plus tracked edits made
since; timestamps alone mislead there, because moving a checkout away and back rewrites
files whose content ends up identical. For any other installation it compares the
service start with the newest source file of the installation the service's own
interpreter imports from. It reads the service record and ``/proc``; it
never starts, restarts or signals anything, and it says "unknown" rather than guess
(not Linux, no running service, or its installation cannot be determined).
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from audiagentic.components.agents.gateway.service.contract import GATEWAY_SERVICE_KEY
from audiagentic.foundation.system.managed_service import ManagedServiceStore

#: Source written within this many seconds of the start is not treated as newer.
_GRACE_SECONDS = 5.0


@dataclass(frozen=True)
class Drift:
    status: str  # "ok" | "drift" | "unknown"
    detail: str
    pid: int | None = None


def process_start_epoch(pid: int) -> float | None:
    """When ``pid`` started, in epoch seconds, from ``/proc``; ``None`` where that cannot be read."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        ticks = int(stat.rsplit(")", 1)[1].split()[19])  # field 22, after the parenthesised command name
        boot = next(int(line.split()[1]) for line in Path("/proc/stat").read_text().splitlines()
                    if line.startswith("btime "))
        return boot + ticks / os.sysconf("SC_CLK_TCK")
    except (OSError, ValueError, IndexError, StopIteration, AttributeError):
        return None


def newest_source_mtime(package_root: Path) -> tuple[float, Path] | None:
    """The most recently modified ``.py`` file under the package, or ``None`` when there is none."""
    newest: tuple[float, Path] | None = None
    for current, directories, files in os.walk(package_root):
        directories[:] = [name for name in directories if name != "__pycache__"]
        for name in files:
            if name.endswith(".py"):
                path = Path(current) / name
                try:
                    modified = path.stat().st_mtime
                except OSError:
                    continue
                if newest is None or modified > newest[0]:
                    newest = (modified, path)
    return newest


def service_package_root(pid: int) -> Path | None:
    """Where the service's own interpreter imports ``audiagentic`` from; ``None`` when that cannot be asked.

    The service command line starts with its interpreter (a virtual environment's python), so asking
    that interpreter, with a clean environment, resolves the same installation the service imported.
    """
    try:
        interpreter = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")[0].decode()
        environment = {key: value for key, value in os.environ.items() if key not in {"PYTHONPATH", "PYTHONHOME"}}
        done = subprocess.run([interpreter, "-I", "-c", "import audiagentic; print(audiagentic.__file__)"],
                              capture_output=True, text=True, timeout=30.0, check=False, env=environment)
    except (OSError, UnicodeDecodeError, subprocess.SubprocessError):
        return None
    line = done.stdout.strip().splitlines()[-1] if done.returncode == 0 and done.stdout.strip() else ""
    return Path(line).resolve().parent if line else None


def _git(root: Path, *args: str) -> str | None:
    try:
        done = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=30.0,
                              check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


def _git_verdict(package_root: Path, started: float, pid: int) -> Drift | None:
    """Drift for a git checkout by commit, or ``None`` when the package is not inside one."""
    top = _git(package_root, "rev-parse", "--show-toplevel")
    if top is None:
        return None
    root = Path(top.strip())
    head = (_git(root, "rev-parse", "HEAD") or "").strip()
    log = _git(root, "reflog", "show", "--date=unix", "--format=%H %gd", "HEAD")
    loaded = None
    for line in (log or "").splitlines():  # newest first: the first entry at or before the start was in effect
        sha, _, selector = line.partition(" ")
        try:
            stamp = int(selector.rsplit("@{", 1)[1].rstrip("}"))
        except (IndexError, ValueError):
            continue
        if stamp <= started + _GRACE_SECONDS:
            loaded = sha
            break
    if not head or loaded is None:
        return Drift("unknown", "the commit that was checked out when the gateway service started cannot be "
                                "found in the reflog", pid)
    if head != loaded:
        return Drift("drift", f"the gateway service (pid {pid}) loaded {loaded[:9]} but {head[:9]} is checked out "
                              "now, so it is running older code than the installation", pid)
    edited = (_git(root, "diff", "--name-only", "HEAD") or "").split()
    changed = [name for name in edited if name.endswith(".py") and (root / name).exists()
               and (root / name).stat().st_mtime > started + _GRACE_SECONDS]
    if changed:
        return Drift("drift", f"{changed[0]} was edited after the gateway service (pid {pid}) started", pid)
    return Drift("ok", f"the gateway service (pid {pid}) runs the commit that is checked out ({head[:9]})", pid)


def check_gateway_code_drift(*, store: ManagedServiceStore | None = None, package_root: Path | None = None,
                             start_epoch=process_start_epoch, package_root_for=service_package_root) -> Drift:
    """Compare the running gateway service's start with the newest source of the code it imported."""
    try:
        record = (store or ManagedServiceStore(GATEWAY_SERVICE_KEY)).read()
    except Exception:  # noqa: BLE001 - no record means no service to compare
        return Drift("ok", "no gateway service record; nothing is running old code")
    if record.state != "running" or record.process is None:
        return Drift("ok", f"the gateway service is {record.state}; nothing is running old code")
    pid = record.process.pid
    started = start_epoch(pid)
    if started is None:
        return Drift("unknown", "the gateway service's start time cannot be read on this platform", pid)
    package_root = package_root or package_root_for(pid)
    if package_root is None:
        return Drift("unknown", "the installation the gateway service imports from cannot be determined", pid)
    by_commit = _git_verdict(package_root, started, pid)
    if by_commit is not None:
        return by_commit
    newest = newest_source_mtime(package_root)
    if newest is None:
        return Drift("unknown", "no source files were found to compare", pid)
    if newest[0] > started + _GRACE_SECONDS:
        return Drift(
            "drift",
            f"{newest[1].relative_to(package_root).as_posix()} changed {int(newest[0] - started)} s after the gateway "
            f"service (pid {pid}) started, so the service is running older code than the installation it was started from",
            pid)
    return Drift("ok", f"the gateway service (pid {pid}) started after the newest source file changed", pid)
