"""Foundation structured logging.

Records follow the OpenTelemetry Logs data model shape closely enough to stay
portable without requiring the OpenTelemetry SDK at runtime.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from audiagentic.foundation.time import now_iso

from .envelope import EventEnvelope

__all__ = ["StructuredLog", "now_iso"]


class StructuredLog:
    """Append-only JSONL structured log using OpenTelemetry-style fields."""

    def __init__(self, path: Path | None):
        self.path = path

    def emit(
        self,
        *,
        body: str,
        attributes: dict[str, Any] | None = None,
        severity_text: str = "INFO",
        timestamp: str | None = None,
        observed_timestamp: str | None = None,
        trace_id: str | None = None,
        span_id: str | None = None,
    ) -> None:
        """Write one log record as JSONL.

        Field names intentionally mirror OpenTelemetry's Logs data model using
        Python-friendly snake_case for JSON consumers in this repository.
        """
        if self.path is None:
            return

        ts = timestamp or now_iso()
        rec: dict[str, Any] = {
            "timestamp": ts,
            "observed_timestamp": observed_timestamp or ts,
            "severity_text": severity_text,
            "body": body,
            "attributes": attributes or {},
        }
        if trace_id:
            rec["trace_id"] = trace_id
        if span_id:
            rec["span_id"] = span_id

        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")

    def emit_event(self, envelope: EventEnvelope) -> None:
        """Write one canonical event record as structured JSONL."""
        attributes: dict[str, Any] = {
            "event.id": envelope.id,
            "event.name": envelope.type,
            "event.version": envelope.version,
            "event.source_component": envelope.source_component,
            "event.is_replay": envelope.is_replay,
            "event.propagation_depth": envelope.propagation_depth,
            "payload": envelope.payload,
            "metadata": envelope.metadata,
        }
        if envelope.correlation_id:
            attributes["event.correlation_id"] = envelope.correlation_id
        if envelope.subject is not None:
            attributes["subject"] = envelope.subject
        self.emit(
            body=envelope.type,
            severity_text="INFO",
            timestamp=envelope.occurred_at,
            observed_timestamp=envelope.occurred_at,
            attributes=attributes,
        )
