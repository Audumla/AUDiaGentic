"""Generic event service.

Publishes events to both the local EventLog and the shared EventBus.
No workflow-specific logic (propagation, automation) lives here.
"""

from __future__ import annotations

import warnings
from typing import Any

from .bus import DeliveryMode, get_bus


class EventService:
    """Publish events to local log and shared bus.

    Workflow-specific behavior (state propagation, automation hooks)
    is implemented as event subscribers, not baked into this service.
    """

    def __init__(self, event_log):
        """Initialize with an EventLog instance.

        Args:
            event_log: EventLog instance for local persistence.
        """
        self.event_log = event_log

    def publish(
        self,
        event_type: str,
        payload: dict[str, Any],
        metadata: dict[str, Any] | None = None,
        mode: str | None = None,
    ) -> None:
        """Publish an event to both local log and shared bus.

        Args:
            event_type: Event type string (e.g., "workflow.item.state.changed").
            payload: Event payload dict.
            metadata: Optional metadata dict.
            mode: Delivery mode override ("sync" or "async"). Defaults to async.
        """
        self.event_log.emit(event_type, payload)

        try:
            bus = get_bus()
            bus.publish(
                event_type=event_type,
                payload=payload,
                metadata=metadata or {},
                mode=(DeliveryMode(mode) if mode else DeliveryMode.ASYNC),
            )
        except Exception as e:
            warnings.warn(f"Event publish failed for {event_type}: {e}", RuntimeWarning)

    @property
    def supports_sync(self) -> bool:
        """Whether synchronous delivery is available."""
        return True

    def sync_delivery_mode(self) -> str | None:
        """Return SYNC delivery mode if available, else None.

        Used by planning lifecycle to force synchronous delivery for
        state changes that must complete before the caller continues.
        """
        return DeliveryMode.SYNC
