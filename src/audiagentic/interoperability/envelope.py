"""Event envelope for canonical event representation."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class EventEnvelope:
    """Canonical event envelope for interoperability layer.

    All events are wrapped in this envelope with auto-generated metadata.

    Attributes:
        id: Unique event ID (auto-generated)
        type: Event type string (e.g., "planning.item.state.changed")
        version: Envelope version (default: 1)
        occurred_at: Timestamp of event occurrence (auto-generated, UTC ISO 8601)
        source_component: Emitting component name (configured default or from metadata)
        correlation_id: Optional correlation ID (from metadata if provided)
        subject: Optional subject identifier (from metadata if provided)
        payload: User-provided payload dict
        metadata: User-provided metadata dict
        is_replay: Boolean flag (auto-set during replay)
        propagation_depth: Integer (auto-incremented during propagation, default: 0)
    """

    type: str
    payload: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)

    # Auto-generated fields
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    version: int = 1
    occurred_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    source_component: str = "unknown"
    correlation_id: str | None = None
    subject: dict[str, Any] | None = None
    is_replay: bool = False
    propagation_depth: int = 0

    def __post_init__(self) -> None:
        """Extract correlation_id, subject, and propagation_depth from metadata if provided."""
        if self.correlation_id is None:
            self.correlation_id = self.metadata.get("correlation_id")
        if self.subject is None:
            self.subject = self.metadata.get("subject")
        if self.propagation_depth == 0:
            self.propagation_depth = self.metadata.get("propagation_depth", 0)

    def to_dict(self) -> dict[str, Any]:
        """Convert envelope to dictionary for serialization."""
        return {
            "id": self.id,
            "type": self.type,
            "version": self.version,
            "occurred_at": self.occurred_at,
            "source_component": self.source_component,
            "correlation_id": self.correlation_id,
            "subject": self.subject,
            "payload": self.payload,
            "metadata": self.metadata,
            "is_replay": self.is_replay,
            "propagation_depth": self.propagation_depth,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EventEnvelope:
        """Create envelope from dictionary."""
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            type=data["type"],
            version=data.get("version", 1),
            occurred_at=data.get("occurred_at", datetime.now(timezone.utc).isoformat()),
            source_component=data.get("source_component", "unknown"),
            correlation_id=data.get("correlation_id"),
            subject=data.get("subject"),
            payload=data.get("payload", {}),
            metadata=data.get("metadata", {}),
            is_replay=data.get("is_replay", False),
            propagation_depth=data.get("propagation_depth", 0),
        )
