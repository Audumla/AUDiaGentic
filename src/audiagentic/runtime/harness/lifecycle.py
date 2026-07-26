"""Shared install-lifecycle glue reused by every harness's install module.

Only the "refresh materialized config, then request a runtime reload" sequence
(and its error handling) is shared here. Each harness still owns its own
CLI-availability check and its own refresh/reload calls -- passed in as
callables so they resolve dynamically against the calling module's own
functions (keeping them independently monkeypatchable in tests, e.g.
``runtime.harness.pi.install.request_runtime_reload``).
"""
from __future__ import annotations

import logging
from collections.abc import Callable

from audiagentic.foundation.contracts.errors import AudiaGenticError

logger = logging.getLogger(__name__)


def refresh_harness_config_if_installed(
    *,
    cli_installed: bool,
    component_id: str | None,
    refresh: Callable[[], None],
    request_reload: Callable[[], None],
) -> bool:
    """Regenerate agent config and request a runtime reload if the harness CLI is present.

    Returns True if the harness was present and the refresh was applied.
    """
    if not cli_installed:
        return False
    refreshed = True
    try:
        refresh()
    except AudiaGenticError:
        logger.warning("Failed to refresh agent config for %s", component_id, exc_info=True, extra={"component": component_id})
        refreshed = False
    try:
        request_reload()
    except AudiaGenticError:
        logger.warning("Failed to request runtime reload for %s", component_id, exc_info=True, extra={"component": component_id})
        refreshed = False
    return refreshed


__all__ = ["refresh_harness_config_if_installed"]
