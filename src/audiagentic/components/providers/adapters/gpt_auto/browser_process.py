"""Conservative browser acquisition for the shared gpt-auto runtime."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from audiagentic.foundation.system.process import (
    find_pid_on_port,
    kill_pid,
    kill_process_tree,
    pid_alive,
)

from .config import BrowserConfig, ExistingBrowserPolicy


@dataclass(frozen=True)
class BrowserProcessEvidence:
    pid: int | None
    creation_identity: str | None
    launched_by_provider: bool


class BrowserProcessController:
    def __init__(
        self,
        config: BrowserConfig,
        *,
        cdp_probe: Callable[[], Awaitable[bool]],
        process_lookup: Callable[[Path], list[int]] | None = None,
        port_owner: Callable[[int], int | None] = find_pid_on_port,
    ) -> None:
        self.config = config
        self._cdp_probe = cdp_probe
        self._process_lookup = process_lookup or _matching_windows_processes
        self._port_owner = port_owner
        self._launched: asyncio.subprocess.Process | None = None

    async def ensure_browser_for_cdp(self) -> BrowserProcessEvidence:
        from .runtime import _gp31_trace

        probe_ok = await self._cdp_probe()
        _gp31_trace(f"ensure_browser_for_cdp(): _cdp_probe()={probe_ok}")
        if probe_ok:
            owner_pid = self._port_owner(self.config.remote_debugging_port)
            _gp31_trace(f"ensure_browser_for_cdp(): probe ok, port_owner={owner_pid} -- reconnect, no launch")
            return BrowserProcessEvidence(owner_pid, None, False)
        owner = self._port_owner(self.config.remote_debugging_port)
        _gp31_trace(f"ensure_browser_for_cdp(): probe failed, port_owner={owner}")
        if owner is not None:
            _gp31_trace("ensure_browser_for_cdp(): raising -- port occupied but not usable CDP")
            raise RuntimeError(
                "configured CDP port is occupied but is not a usable browser endpoint"
            )
        matching = self._process_lookup(self.config.executable)
        _gp31_trace(f"ensure_browser_for_cdp(): matching processes={matching}")
        if matching:
            if self.config.existing_browser_policy is ExistingBrowserPolicy.FAIL:
                _gp31_trace("ensure_browser_for_cdp(): raising -- FAIL policy, matching process exists")
                raise RuntimeError("configured browser is running without usable CDP")
            # Executable identity is not ownership evidence. A restart policy
            # must never terminate unrelated user windows; only a process
            # launched and recorded by this controller may be stopped.
            _gp31_trace("ensure_browser_for_cdp(): raising -- restart refused, ownership unproven")
            raise RuntimeError(
                "configured browser is running without usable CDP; restart refused "
                "because process ownership cannot be proven"
            )
        _gp31_trace("ensure_browser_for_cdp(): NO matching process found -- launching a FRESH browser")
        self._launched = await asyncio.create_subprocess_exec(
            str(self.config.executable),
            f"--remote-debugging-port={self.config.remote_debugging_port}",
        )
        _gp31_trace(f"ensure_browser_for_cdp(): launched fresh browser pid={self._launched.pid}")
        return BrowserProcessEvidence(self._launched.pid, None, True)

    async def _stop_matching(self, pids: list[int]) -> None:
        for pid in pids:
            kill_pid(pid)
        deadline = asyncio.get_running_loop().time() + self.config.shutdown_timeout_seconds
        while any(pid_alive(pid) for pid in pids) and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.1)
        alive = [pid for pid in pids if pid_alive(pid)]
        if not alive:
            return
        if not self.config.force_kill:
            raise RuntimeError("configured browser did not stop before shutdown timeout")
        for pid in alive:
            kill_process_tree(pid)

    async def shutdown(self) -> None:
        """Stop only the browser process launched by this controller."""
        proc, self._launched = self._launched, None
        if proc is None or proc.returncode is not None:
            return
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), self.config.shutdown_timeout_seconds)
        except TimeoutError:
            if not self.config.force_kill:
                raise RuntimeError("provider-launched browser did not stop before timeout")
            kill_process_tree(proc.pid)
            await proc.wait()


def _matching_windows_processes(executable: Path) -> list[int]:
    escaped = str(executable).replace("'", "''")
    command = (
        "Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -eq '"
        + escaped
        + "' } | Select-Object -ExpandProperty ProcessId"
    )
    import subprocess

    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        check=False,
    )
    return [int(line) for line in result.stdout.splitlines() if line.strip().isdigit()]
