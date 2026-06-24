"""Propagation log recording for state transitions."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .log import PropagationLog

logger = logging.getLogger(__name__)


class LogRecorder:
    """Record propagation events to the propagation log."""

    def __init__(self, ctx: Any, log_path: Path | None = None) -> None:
        self.ctx = ctx
        self._log = PropagationLog(log_path)

    def record(
        self,
        status: str,
        target_id: str,
        target_state: str,
        source_id: str,
        source_state: str,
        metadata: dict[str, Any],
        *,
        target_kind: str | None = None,
        old_state: str | None = None,
        reason: str | None = None,
    ) -> None:
        source_view = self.ctx.lookup(source_id)
        source_kind = None
        if source_view:
            source_kind = getattr(source_view, "kind", None)
            if source_kind is None and source_view.data:
                source_kind = source_view.data.get("kind")
        self._log.append(
            status=status,
            target_id=target_id,
            target_state=target_state,
            source_id=source_id,
            source_kind=source_kind,
            source_state=source_state,
            metadata=metadata,
            target_kind=target_kind,
            old_state=old_state,
            reason=reason,
        )
