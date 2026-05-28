"""Propagation attempt audit log."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from audiagentic.foundation.event.log import StructuredLog

logger = logging.getLogger(__name__)


class PropagationLog:
    def __init__(self, path: Path | None):
        self._log = StructuredLog(path)

    def append(
        self,
        *,
        status: str,
        target_id: str,
        target_state: str,
        source_id: str,
        source_kind: str | None,
        source_state: str,
        metadata: dict[str, Any],
        target_kind: str | None = None,
        old_state: str | None = None,
        reason: str | None = None,
    ) -> None:
        attributes: dict[str, Any] = {
            "event.name": f"workflow.propagation.{status}",
            "event.domain": "workflow",
            "event.action": "propagate",
            "event.outcome": status,
            "workflow.source.kind": source_kind,
            "workflow.source.id": source_id,
            "workflow.source.state": source_state,
            "workflow.target.kind": target_kind,
            "workflow.target.id": target_id,
            "workflow.target.old_state": old_state,
            "workflow.target.new_state": target_state,
            "workflow.triggered_by": metadata.get("triggered_by", "automatic"),
            "workflow.propagation_depth": metadata.get("propagation_depth", 0),
            "correlation_id": metadata.get("correlation_id"),
            "event_id": metadata.get("correlation_id") or metadata.get("event_id"),
        }
        if reason:
            attributes["workflow.reason"] = reason

        try:
            self._log.emit(
                body=f"workflow.propagation.{status}",
                severity_text="ERROR" if status == "failed" else "INFO",
                attributes=attributes,
            )
        except Exception:
            logger.warning("Failed to write propagation log entry for %s", target_id, exc_info=True)
