"""Project-scoped registry for shared gpt-auto runtimes."""

from __future__ import annotations

import asyncio
from pathlib import Path

from .config import GptAutoConfig
from .runtime import GptAutoProviderRuntime

_runtimes: dict[Path, GptAutoProviderRuntime] = {}


def get_runtime(project_root: Path, config: GptAutoConfig) -> GptAutoProviderRuntime:
    key = project_root.resolve()
    current = _runtimes.get(key)
    if current is not None:
        if current.config != config:
            raise RuntimeError("gpt-auto configuration changed while runtime is active")
        return current
    current = GptAutoProviderRuntime(config)
    _runtimes[key] = current
    return current


async def shutdown_runtime(project_root: Path) -> None:
    runtime = _runtimes.pop(project_root.resolve(), None)
    if runtime:
        await runtime.shutdown()


async def shutdown_all_runtimes() -> None:
    runtimes = list(_runtimes.values())
    _runtimes.clear()
    await asyncio.gather(*(runtime.shutdown() for runtime in runtimes), return_exceptions=True)
