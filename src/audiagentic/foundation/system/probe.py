"""Generic binary probe utilities for component capability detection."""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field


@dataclass
class ProbeSpec:
    name: str
    requires: tuple[str, ...]
    probe_cmd: list[str] | None = field(default=None)


def probe_binary(
    name: str,
    requires: tuple[str, ...],
    probe_cmd: list[str] | None = None,
    timeout: float = 5.0,
) -> bool:
    """Return True if all *requires* binaries are on PATH and *probe_cmd* exits 0.

    If *probe_cmd* is None, presence on PATH is sufficient.
    """
    if any(shutil.which(r) is None for r in requires):
        return False
    if probe_cmd is None:
        return True
    try:
        result = subprocess.run(probe_cmd, capture_output=True, timeout=timeout)
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def probe_servers(servers: list[ProbeSpec]) -> dict[str, bool]:
    """Probe each server spec and return a name → available mapping."""
    return {s.name: probe_binary(s.name, s.requires, s.probe_cmd) for s in servers}
