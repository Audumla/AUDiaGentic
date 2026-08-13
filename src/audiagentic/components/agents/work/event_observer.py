"""Canonical event-trigger observer for Agent Work.

This module owns trigger subscription and evaluation at the Agents boundary.
The observer deliberately has no dependency on the retired ``agent_jobs``
component; lifecycle and failure state are recorded as Agents operational
evidence while Work owns execution state.
"""
from __future__ import annotations

import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from audiagentic.foundation.event.event_bus import SubscriptionHandle, get_bus
from audiagentic.foundation.event.lifecycle_observer import subscribe_component_lifecycle
from audiagentic.foundation.logging.context import get_correlation_id, new_correlation_id
from audiagentic.foundation.observability.operational_records import append_operational_record
from audiagentic.foundation.time import now_iso_z

from .event_ingress import WorkEventIngress
from .triggers import trigger_matches

logger = logging.getLogger(__name__)
_AUDIT_PATH = Path(".audiagentic") / "runtime" / "agents" / "trigger-audit.ndjson"

GW_TOPIC_REQUESTED = "agents.execution.gateway.requested"
GW_TOPIC_CANCEL_REQUESTED = "agents.execution.gateway.cancel-requested"
GW_OUTCOME_TOPICS = (
    "agents.execution.completed",
    "agents.execution.failed",
    "agents.execution.rejected",
    "agents.execution.cancelled",
    "agents.execution.interrupted",
)


def _audit(project_root: Path, *, trigger_id: str, event_type: str, status: str,
           correlation_id: str = "", work_id: str | None = None,
           reason: str | None = None, error_code: str | None = None) -> None:
    record: dict[str, Any] = {
        "timestamp": now_iso_z(), "trigger_id": trigger_id,
        "event_type": event_type, "correlation_id": correlation_id,
        "status": status, "job_id": work_id, "error_code": error_code,
    }
    if reason is not None:
        record["reason"] = reason
    append_operational_record(project_root / _AUDIT_PATH, record)


class EventObserver:
    """Compatibility-named observer backed entirely by canonical Work ingress."""

    GW_OUTCOME_MAP = {
        "agents.execution.completed": "completed",
        "agents.execution.failed": "failed",
        "agents.execution.rejected": "failed",
        "agents.execution.cancelled": "cancelled",
        "agents.execution.interrupted": "failed",
    }

    def __init__(self, *, context_id: str | None = None) -> None:
        self._context_id = context_id
        self._project_root: Path | None = None
        self._ingress: WorkEventIngress | None = None
        self._handles: list[SubscriptionHandle] = []
        self._subscribed = False

    def initialize(self, project_root: Path, *, context_id: str | None = None) -> None:
        if self._subscribed:
            return
        if context_id is not None:
            self._context_id = context_id
        self._project_root = project_root.resolve()
        if not self._context_id:
            raise ValueError("event trigger dispatch requires context_id")
        self._ingress = WorkEventIngress.from_project_config(
            self._project_root, context_id=self._context_id
        )
        for trigger in self._ingress._triggers:  # subscriptions remain owned here
            pattern = trigger.get("event-pattern", trigger.get("event_pattern"))
            if isinstance(pattern, str) and pattern:
                self._handles.append(get_bus().subscribe(pattern, self._handler(trigger)))
        self._subscribed = True

    def stop(self) -> None:
        for handle in self._handles:
            get_bus().unsubscribe(handle)
        self._handles.clear()
        self._subscribed = False

    def _handler(self, trigger: Mapping[str, Any]):
        def handle(event_type: str, payload: dict[str, Any], metadata: dict[str, Any]) -> None:
            root = self._project_root
            ingress = self._ingress
            if root is None or ingress is None:
                return
            correlation_id = str(
                metadata.get("correlation-id") or metadata.get("correlation_id")
                or get_correlation_id() or new_correlation_id()
            )
            event_metadata = {**metadata, "correlation_id": correlation_id}
            trigger_id = str(trigger.get("trigger-id", trigger.get("trigger_id", "event")))
            if not trigger_matches(trigger, event_type=event_type, payload=payload, metadata=event_metadata):
                _audit(root, trigger_id=trigger_id, event_type=event_type,
                       correlation_id=correlation_id, status="suppressed", reason="filter-or-disabled")
                return
            try:
                record = ingress.submit(trigger, event_type, payload, event_metadata)
                if record is not None:
                    _audit(root, trigger_id=trigger_id, event_type=event_type,
                           correlation_id=correlation_id, status="fired", work_id=record.work_id)
            except Exception as exc:  # noqa: BLE001 - event-bus isolation boundary
                logger.error("Canonical event Work submission failed", exc_info=exc)
                _audit(root, trigger_id=trigger_id, event_type=event_type,
                       correlation_id=correlation_id, status="failed",
                       error_code=getattr(exc, "code", "INT-AGW-EVENT-001"))
        return handle


_observer_instance: EventObserver | None = None


def get_event_observer(project_root: Path, *, context_id: str | None = None) -> EventObserver:
    global _observer_instance
    if _observer_instance is None:
        _observer_instance = EventObserver(context_id=context_id)
    if context_id is not None:
        _observer_instance._context_id = context_id
    if not _observer_instance._subscribed and _observer_instance._context_id:
        _observer_instance.initialize(project_root)
    return _observer_instance


def _initialize_for_component_lifecycle(project_root: Path, _payload: dict, metadata: dict) -> None:
    # Lifecycle events may not carry a context. In that case startup is deferred
    # until the public observer is created by the owning Agent Context.
    context_id = metadata.get("context-id") or metadata.get("context_id")
    if context_id:
        get_event_observer(project_root, context_id=str(context_id))


subscribe_component_lifecycle(
    "agents", on_installed=_initialize_for_component_lifecycle,
    on_enabled=_initialize_for_component_lifecycle,
    on_config_changed=_initialize_for_component_lifecycle,
)
