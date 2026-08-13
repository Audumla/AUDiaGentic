"""Machine-scoped registry for shared gpt-auto browser runtimes."""

from __future__ import annotations

import asyncio
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
        # Only browser/CDP ownership is machine-scoped. Project workflow,
        # timeouts and URLs stay on each PersistentChat.
        if (current.config.browser, current.config.cdp) != (config.browser, config.cdp):
            raise RuntimeError("gpt-auto machine runtime configuration changed while active")
        return current
    current = GptAutoProviderRuntime(config)
    _runtimes[key] = current
    return current


async def shutdown_runtime(project_root: Path) -> None:
    del project_root
    # A shared runtime is owned by the gateway process; individual project
    # teardown must not close the browser window used by other projects.


async def shutdown_all_runtimes() -> None:
    entries = list(_runtimes.items())
    if not entries:
        return
    results = await asyncio.gather(
        *(runtime.shutdown_from_owner() for _, runtime in entries), return_exceptions=True
    )
    failures: list[Exception] = []
    for (key, _runtime), result in zip(entries, results, strict=True):
        if isinstance(result, BaseException):
            _runtimes[key] = _runtime
            failures.append(
                result
                if isinstance(result, Exception)
                else RuntimeError(f"gpt-auto runtime shutdown was cancelled: {result!r}")
            )
        else:
            _runtimes.pop(key, None)
    if failures:
        raise ExceptionGroup("gpt-auto runtime shutdown failed", failures)
