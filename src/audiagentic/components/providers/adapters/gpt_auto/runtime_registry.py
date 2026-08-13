"""Machine-scoped registry for shared gpt-auto browser runtimes."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

from .config import GptAutoConfig
from .runtime import GptAutoProviderRuntime

_runtimes: dict[tuple[str, int, str], GptAutoProviderRuntime] = {}


def _shared_key(config: GptAutoConfig) -> tuple[str, int, str]:
    """Identify the browser/CDP resource shared by all project sessions."""
    return (
        str(config.browser.executable).lower(),
        config.browser.remote_debugging_port,
        config.cdp_url,
    )


def get_runtime(project_root: Path, config: GptAutoConfig) -> GptAutoProviderRuntime:
    del project_root  # project identity belongs to each chat, not the browser runtime
    key = _shared_key(config)
    current = _runtimes.get(key)
    if current is not None:
        # Project URLs/workflow identity belong to individual chats; transport
        # and browser settings must remain stable for the shared runtime.
        if replace(current.config, project_url=None) != replace(config, project_url=None):
            raise RuntimeError("gpt-auto configuration changed while runtime is active")
        return current
    current = GptAutoProviderRuntime(config)
    _runtimes[key] = current
    return current


async def shutdown_runtime(project_root: Path) -> None:
    del project_root
    # A shared runtime is owned by the gateway process; individual project
    # teardown must not close the browser window used by other projects.


async def shutdown_all_runtimes() -> None:
    runtimes = list(_runtimes.values())
    _runtimes.clear()
    await asyncio.gather(*(runtime.shutdown() for runtime in runtimes), return_exceptions=True)
