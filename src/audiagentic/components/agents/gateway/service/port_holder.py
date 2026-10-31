"""Who holds the gateway's port when this home has no running gateway? (read-only)

The shared gateway binds one TCP port while its service record lives under the AUDiaGentic
home. A client using a different home sees no record, tries to start a second service and
fails on the held port. This reports that case with the holder's pid, command and home so the
fix is a named setting, not a hunt. It connects once to loopback and reads ``/proc``; it
starts, stops and signals nothing, and "unknown" is a valid answer where ``/proc`` is not
readable.
"""
from __future__ import annotations

import os
import socket
from dataclasses import dataclass
from pathlib import Path

from audiagentic.components.agents.gateway.service.contract import GATEWAY_SERVICE_KEY
from audiagentic.foundation.system.managed_service import ManagedServiceStore

_DEFAULT_PORT = 8765
_LISTEN = "0A"


@dataclass(frozen=True)
class Holder:
    pid: int | None = None
    command: str | None = None
    home: str | None = None


@dataclass(frozen=True)
class PortFinding:
    status: str  # "ok" | "held-by-other" | "unknown"
    detail: str
    port: int = 0
    holder: Holder | None = None


def port_in_use(port: int, *, timeout: float = 0.5) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(timeout)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def _listening_inodes(port: int) -> set[str]:
    inodes: set[str] = set()
    for table in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            lines = Path(table).read_text(encoding="utf-8").splitlines()[1:]
        except OSError:
            continue
        for line in lines:
            fields = line.split()
            if len(fields) > 9 and fields[3] == _LISTEN and int(fields[1].rsplit(":", 1)[1], 16) == port:
                inodes.add(fields[9])
    return inodes


def find_holder(port: int) -> Holder | None:
    """The process listening on ``port`` with its command and _AUDIAGENTIC_HOME, or ``None`` if unreadable."""
    inodes = _listening_inodes(port)
    if not inodes:
        return None
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        sockets: set[str] = set()
        try:
            descriptors = list((entry / "fd").iterdir())
        except OSError:
            continue
        for descriptor in descriptors:
            try:
                sockets.add(os.readlink(descriptor))
            except OSError:  # a descriptor closed while listing (the listing's own handle, for one)
                continue
        if not any(f"socket:[{inode}]" in sockets for inode in inodes):
            continue
        pid = int(entry.name)
        try:
            command = (entry / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace").strip()
        except OSError:
            command = None
        home = None
        try:
            for item in (entry / "environ").read_bytes().split(b"\0"):
                if item.startswith(b"_AUDIAGENTIC_HOME="):
                    home = item.split(b"=", 1)[1].decode(errors="replace")
        except OSError:
            pass
        return Holder(pid, command, home)
    return None


def _own_service_running(store: ManagedServiceStore) -> bool:
    try:
        record = store.read()
    except Exception:  # noqa: BLE001 - no record, no own service
        return False
    return record.state == "running" and record.process is not None


def check_gateway_port(*, port: int | None = None, home: Path | None = None,
                       store: ManagedServiceStore | None = None, in_use=port_in_use,
                       holder_of=find_holder) -> PortFinding:
    """Explain a gateway port that something else holds while this home has no running gateway."""
    if port is None:
        from audiagentic.components.agents.gateway.settings import gateway_setting

        port = int(gateway_setting("port", _DEFAULT_PORT))
    if home is None:
        from audiagentic.foundation.paths.names import home_directory

        home = home_directory()
    if _own_service_running(store or ManagedServiceStore(GATEWAY_SERVICE_KEY)):
        return PortFinding("ok", f"this home's gateway service is running (port {port})", port)
    if not in_use(port):
        return PortFinding("ok", f"port {port} is free; the gateway starts on demand", port)
    holder = holder_of(port)
    if holder is None:
        return PortFinding("unknown", f"port {port} is in use but its holder cannot be identified here", port)
    if holder.home and Path(holder.home).resolve() != Path(home).resolve():
        return PortFinding(
            "held-by-other",
            f"port {port} is held by pid {holder.pid} running from the home {holder.home}, not this home ({home})",
            port, holder)
    return PortFinding(
        "held-by-other",
        f"port {port} is held by pid {holder.pid} ({holder.command or 'unknown command'}), which has no "
        f"gateway service record in this home ({home})", port, holder)
