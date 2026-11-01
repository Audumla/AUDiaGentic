"""Pi probes (SH56): does a running interactive Pi expose anything an outside caller could attach to?

A real interactive Pi runs in a pty in a disposable environment and its own process tree is inspected for listening
TCP sockets and unix sockets. ``pi --mode rpc`` is measured too, to record that its protocol belongs to a process
the caller starts. No model is contacted (offline, no provider configured). Only processes this module started are
ever signalled. A missing endpoint is an ``unsupported`` finding for every join capability, not a gap to bridge.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

from audiagentic.components.providers.adapters.pi.join import rpc_get_state

from ..live import CAPABILITIES, LiveContext, ProbeOutcome
from .codex_tui import HumanTui

PROBE_VERSION = "1"
REASON = "unsupported-no-existing-session-endpoint"
_ENV_ALLOWLIST = ("PATH", "LANG", "LC_ALL", "LC_CTYPE")


def _env(root: Path) -> dict[str, str]:
    for name in ("home", "xdg-config", "xdg-data", "xdg-cache", "xdg-state", "tmp"):
        (root / name).mkdir(parents=True, exist_ok=True)
    env = {key: os.environ[key] for key in _ENV_ALLOWLIST if key in os.environ}
    env.update({"HOME": str(root / "home"), "XDG_CONFIG_HOME": str(root / "xdg-config"),
                "XDG_DATA_HOME": str(root / "xdg-data"), "XDG_CACHE_HOME": str(root / "xdg-cache"),
                "XDG_STATE_HOME": str(root / "xdg-state"), "TMPDIR": str(root / "tmp"), "PI_OFFLINE": "1"})
    return env


def _children(pid: int) -> list[int]:
    found = [pid]
    try:
        for child in Path(f"/proc/{pid}/task/{pid}/children").read_text().split():
            found += _children(int(child))
    except OSError:
        pass
    return found


def _socket_inodes(pids: list[int]) -> set[str]:
    inodes: set[str] = set()
    for pid in pids:
        try:
            for fd in os.listdir(f"/proc/{pid}/fd"):
                target = os.readlink(f"/proc/{pid}/fd/{fd}")
                if target.startswith("socket:["):
                    inodes.add(target[8:-1])
        except OSError:
            continue
    return inodes


def listening_endpoints(pids: list[int]) -> tuple[int, int]:
    """(inet listeners, unix sockets) held by exactly these processes."""
    inodes = _socket_inodes(pids)
    inet = 0
    for table in ("tcp", "tcp6"):
        for line in Path(f"/proc/net/{table}").read_text().splitlines()[1:]:
            cols = line.split()
            if len(cols) > 9 and cols[3] == "0A" and cols[9] in inodes:
                inet += 1
    unix = sum(1 for line in Path("/proc/net/unix").read_text().splitlines()[1:]
               if len(line.split()) > 6 and line.split()[6] in inodes)
    return inet, unix


def run(context: LiveContext) -> list[ProbeOutcome]:
    root, workspace = context.root, context.root / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    env = _env(root)
    tui: HumanTui | None = None
    try:
        rpc_state = rpc_get_state(env, workspace)
        tui = HumanTui(Path("pi"), Path("-"), env, workspace,
                       argv=["pi", "--offline", "--no-extensions", "--no-mcp", "--no-session"]).start(settle=10)
        time.sleep(1)
        alive = tui.alive
        inet, unix = listening_endpoints(_children(tui.pid)) if alive and tui.pid else (0, 0)
    except Exception as error:  # noqa: BLE001 - a failed step proves nothing
        return [ProbeOutcome(name, False, "probe-failed", {"error": type(error).__name__}) for name in CAPABILITIES]
    finally:
        if tui is not None:
            tui.stop()
    if not alive:  # no running instance was observed: say nothing about endpoints
        return [ProbeOutcome(name, False, "probe-failed", {"step": "interactive-pi-not-running"}) for name in CAPABILITIES]
    observations = {"probe-version": PROBE_VERSION, "interactive-pi-running": True, "inet-listeners": inet,
                    "unix-sockets": unix, "rpc-get-state-answered": rpc_state is not None,
                    "rpc-transport": "stdio-jsonl-of-a-process-the-caller-starts"}
    unsupported = inet == 0 and unix == 0
    reason = REASON if unsupported else "unproven-endpoint-present-but-not-examined"
    return [ProbeOutcome(name, False, reason, dict(observations)) for name in CAPABILITIES]
