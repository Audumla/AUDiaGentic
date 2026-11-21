"""Keep the idle-tab reaper alive while the gateway is up, with or without requests.

The reaper starts when the shared runtime attaches to the browser, which used to happen only on the first
request or dedicated-window use. A gateway that restarted with nothing queued never attached, so leased tabs
past their idle timeout stayed open indefinitely. The gateway calls this pass periodically on the session
loop; it only attaches to a browser that is already running and never launches one.
"""
from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from .config import GptAutoConfig
from .conversation_focus import _provider_settings
from .runtime_registry import get_runtime


async def attach_for_tab_maintenance(project_roots: Sequence[Path]) -> bool:
    """Attach the shared runtime to a running browser so its reaper runs; True when attached.

    The first project whose configuration resolves wins, as it would for a first request: the browser runtime
    is machine-scoped and every project shares it.
    """
    for root in project_roots:
        try:
            config = GptAutoConfig.from_project_dict(_provider_settings(root, "gpt-auto"))
        except Exception:  # noqa: BLE001 - one unreadable project must not stop the pass
            continue
        return await get_runtime(root, config).connect_existing()
    return False
