"""Stop gateway services a test started, so a leaked service never outlives pytest.

A managed gateway service is detached on purpose and survives its parent. With the
shared (``automatic``) implementation as the default, a service left behind by a
test holds the gateway port and blocks every real client. Only a process whose
``AUDIAGENTIC_HOME`` is exactly the test's temp home is stopped.
"""
from __future__ import annotations

from pathlib import Path

import psutil

_SERVICE_MODULE = "audiagentic.components.agents.gateway.service.process"


def stop_gateway_services(home: Path, *, timeout: float = 5.0) -> list[int]:
    """Terminate (then kill) gateway service processes started with ``AUDIAGENTIC_HOME=home``."""
    victims = []
    for process in psutil.process_iter(["pid", "cmdline"]):
        try:
            if not any(_SERVICE_MODULE in part for part in process.info["cmdline"] or []):
                continue
            if process.environ().get("AUDIAGENTIC_HOME") != str(home):
                continue
            victims.append(process)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    for process in victims:
        try:
            process.terminate()
        except psutil.NoSuchProcess:
            pass
    _gone, alive = psutil.wait_procs(victims, timeout=timeout)
    for process in alive:
        try:
            process.kill()
        except psutil.NoSuchProcess:
            pass
    psutil.wait_procs(alive, timeout=timeout)
    return [process.pid for process in victims]
