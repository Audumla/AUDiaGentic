"""The process's single composed root: startup and shutdown, nothing else.

The host owns *when* process-level startup happens and *what order* it happens
in. It owns no business logic, is never injected into a domain service, and is
not a façade — the calls it makes into unmigrated code are ordinary function
calls to existing modules, not a lookup surface.

Per AS59's bounded legacy exemption, `start()` still invokes the existing
logging and harness-status bootstrap paths directly. Those keep their current
construction until an item materially refactors them; the exemption is what
lets that be true without adding a second startup path.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class ApplicationHost:
    """Composed process lifetime for the `audiagentic` CLI.

    `interaction_backend` is injected rather than constructed here — it is the
    first service this process composes rather than instantiates at its call
    site, and the reason the graph has a real edge to validate.
    """

    def __init__(self, *, interaction_backend: Any) -> None:
        self._interaction_backend = interaction_backend
        self._started = False
        self._project_root: Path | None = None
        self._command: str | None = None

    def start(
        self,
        *,
        project_root: Path,
        command: str | None,
        harness_status_functions: Callable[[], dict[str, Callable[..., Any]]],
    ) -> None:
        """Bring the process up. Idempotent.

        `harness_status_functions` is passed as a callable, not a dict, to keep
        the `audiagentic.runtime.harness` import deferred to exactly the point
        it happened before — resolving it eagerly here would pull the harness
        package into every CLI invocation that never needs it.
        """
        if self._started:
            return
        self._started = True
        self._project_root = project_root
        self._command = command

        from audiagentic.foundation.interaction import set_backend
        from audiagentic.foundation.logging import bootstrap as log_bootstrap

        log_bootstrap("harness", project_root=project_root)
        set_backend(self._interaction_backend)

        logger.info(
            "audiagentic started",
            extra={"project_root": str(project_root), "command": command},
        )

        # RU02: wire harness-status before any product component resolves it.
        # Product components depend on foundation/capabilities, not runtime.harness.
        from audiagentic.foundation.capabilities import register_harness_status

        register_harness_status(harness_status_functions())

    def shutdown(self) -> None:
        """Record process exit. Idempotent, and safe after logging teardown."""
        if not self._started:
            return
        self._started = False
        handlers = list(logging.getLogger().handlers) + list(logger.handlers)
        if any(getattr(getattr(handler, "stream", None), "closed", False) for handler in handlers):
            return
        logger.info(
            "audiagentic exit",
            extra={"project_root": str(self._project_root), "command": self._command},
        )
