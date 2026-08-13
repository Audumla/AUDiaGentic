"""Compatibility observer delegating event triggers to canonical Agents Work."""
from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from audiagentic.components.agent_jobs.dead_letter import write_dead_letter
from audiagentic.components.agent_jobs.event_triggers import (
    TriggerConfig,
    load_event_triggers,
    matches_filter,
)
from audiagentic.components.agent_jobs.prompt_context import (
    build_prompt_context_from_event,
    to_template_dict,
)
from audiagentic.components.agent_jobs.prompt_templates import render_prompt_template
from audiagentic.components.agents.work.event_adapter import dispatch_trigger_event
from audiagentic.components.agents.work.ingress import deterministic_work_id
from audiagentic.foundation.contracts.errors import AudiaGenticError, make_error_factory
from audiagentic.foundation.event.envelope import EventEnvelope
from audiagentic.foundation.event.event_bus import SubscriptionHandle, get_bus
from audiagentic.foundation.event.lifecycle_observer import subscribe_component_lifecycle
from audiagentic.foundation.logging.context import (
    get_correlation_id as _get_ctx_correlation_id,
)
from audiagentic.foundation.logging.context import (
    new_correlation_id as _new_correlation_id,
)
from audiagentic.foundation.logging.redaction import redact_text, safe_metadata, summarize_structure
from audiagentic.foundation.observability.operational_records import append_operational_record
from audiagentic.foundation.time import now_iso_z

logger = logging.getLogger(__name__)
_eob_error = make_error_factory("CON", "EOB", "event-observer-subscription")
_TRIGGER_AUDIT_PATH = Path(".audiagentic") / "runtime" / "agent-jobs" / "trigger-audit.ndjson"

# Stable string mirrors retained for boundary/conformance consumers.  The
# canonical topic ownership remains in the Agents component; these constants
# avoid importing that component back into the compatibility adapter.
GW_TOPIC_REQUESTED = "agents.execution.gateway.requested"
GW_TOPIC_CANCEL_REQUESTED = "agents.execution.gateway.cancel-requested"
GW_OUTCOME_TOPICS = (
    "agents.execution.completed",
    "agents.execution.failed",
    "agents.execution.rejected",
    "agents.execution.cancelled",
    "agents.execution.interrupted",
)


class EventObserver:
    """Observe legacy trigger config and submit canonical Work exactly once."""

    # Compatibility mirror for consumers that still inspect the old observer
    # contract.  It is descriptive only: canonical Work owns the lifecycle
    # transition and this adapter never applies the mapped state.
    GW_OUTCOME_MAP = {
        "agents.execution.completed": "completed",
        "agents.execution.failed": "failed",
        "agents.execution.rejected": "failed",
        "agents.execution.cancelled": "cancelled",
        "agents.execution.interrupted": "failed",
    }

    def __init__(self, *, context_id: str | None = None) -> None:
        self._subscribed = False
        self._project_root: Path | None = None
        self._handles: list[SubscriptionHandle] = []
        self._triggers: list[TriggerConfig] = []
        self._context_id = context_id

    def initialize(self, project_root: Path, *, context_id: str | None = None) -> None:
        """Load triggers and subscribe once; outcomes belong to canonical Work."""
        if self._subscribed:
            return
        self._project_root = project_root.resolve()
        if context_id is not None:
            self._context_id = context_id
        try:
            self._triggers = load_event_triggers(self._project_root)
        except AudiaGenticError:
            raise
        except Exception as exc:  # noqa: BLE001 - lifecycle boundary
            logger.error("Failed to load event triggers", exc_info=exc)
            _write_trigger_audit(
                self._project_root,
                trigger_id=None,
                event_type=None,
                correlation_id=None,
                status="failed",
                error_code="IO-TRIG-001",
                error_message=str(exc),
            )
            return

        bus = get_bus()
        for trigger in self._triggers:
            if not trigger.event_pattern:
                continue
            try:
                self._handles.append(bus.subscribe(trigger.event_pattern, self._make_handler(trigger)))
            except Exception as exc:  # noqa: BLE001 - subscription boundary
                logger.error("Failed to subscribe to %r", trigger.event_pattern, exc_info=exc)
                _write_trigger_audit(
                    self._project_root,
                    trigger_id=trigger.trigger_id,
                    event_type=trigger.event_pattern,
                    correlation_id=None,
                    status="failed",
                    error_code="CON-EOB-001",
                    error_message=str(exc),
                )
        self._subscribed = True

    def _make_handler(self, trigger: TriggerConfig) -> Callable[[str, dict[str, Any], dict[str, Any]], None]:
        def handler(event_type: str, payload: dict[str, Any], metadata: dict[str, Any]) -> None:
            self._on_trigger_match(trigger, event_type, payload, metadata)

        return handler

    def _on_trigger_match(
        self,
        trigger_config: TriggerConfig,
        event_type: str,
        payload: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> None:
        root = self._project_root
        if root is None:
            logger.error("EventObserver not initialized; cannot dispatch event")
            return
        event_metadata = dict(metadata or {})
        correlation_id = event_metadata.get("correlation-id") or event_metadata.get("correlation_id")
        correlation_id = correlation_id or _get_ctx_correlation_id() or _new_correlation_id()
        event_metadata["correlation_id"] = correlation_id
        if not trigger_config.enabled:
            _write_trigger_audit(root, trigger_id=trigger_config.trigger_id, event_type=event_type,
                                 correlation_id=correlation_id, status="suppressed")
            return
        if trigger_config.filter and not matches_filter({"payload": payload, "metadata": event_metadata}, trigger_config.filter):
            _write_trigger_audit(root, trigger_id=trigger_config.trigger_id, event_type=event_type,
                                 correlation_id=correlation_id, status="suppressed", reason="filter")
            return
        try:
            self._dispatch(trigger_config, event_type, payload, event_metadata, str(correlation_id))
        except Exception as exc:  # noqa: BLE001 - subscriber isolation boundary
            logger.error("Canonical event Work submission failed", exc_info=exc)
            try:
                write_dead_letter(root, {
                    "event_type": event_type,
                    "payload_summary": summarize_structure(payload) if payload else "",
                    "metadata": safe_metadata(event_metadata),
                    "trigger_id": trigger_config.trigger_id,
                    "job_id": None,
                    "error_code": getattr(exc, "code", "INT-EVT-001"),
                    "error_message": redact_text(str(exc)),
                    "correlation_id": correlation_id,
                })
            finally:
                _write_trigger_audit(root, trigger_id=trigger_config.trigger_id, event_type=event_type,
                                     correlation_id=correlation_id, status="failed",
                                     error_code=getattr(exc, "code", "INT-EVT-001"),
                                     error_message=str(exc)[:500])

    def _dispatch(
        self,
        trigger_config: TriggerConfig,
        event_type: str,
        payload: dict[str, Any],
        metadata: dict[str, Any],
        correlation_id: str,
    ) -> None:
        root = self._project_root
        assert root is not None
        delivery_id = str(
            metadata.get("event-id") or metadata.get("event_id")
            or metadata.get("delivery-id") or metadata.get("delivery_id")
            or f"{event_type}:{correlation_id}:{trigger_config.trigger_id}"
        )
        work_id = deterministic_work_id(
            source=f"event-trigger:{trigger_config.trigger_id}", delivery_id=delivery_id
        )
        context_id = metadata.get("context-id") or metadata.get("context_id") or self._context_id
        if not isinstance(context_id, str) or not context_id:
            raise ValueError("event trigger dispatch requires context-id metadata or observer context_id")
        envelope = EventEnvelope(
            type=event_type,
            payload=payload,
            metadata=metadata,
            source_component=metadata.get("source-component", "agent-jobs"),
            correlation_id=correlation_id,
            subject=metadata.get("subject") if isinstance(metadata.get("subject"), dict) else None,
        )
        prompt_context = build_prompt_context_from_event(
            envelope=envelope,
            trigger_config={"trigger_id": trigger_config.trigger_id,
                            "event_pattern": trigger_config.event_pattern,
                            "kind": trigger_config.kind},
            project_root=str(root), project_id="", job_id=work_id,
            execution_profile_id=trigger_config.execution_profile_id or "",
            provider_id="", model_id="", target=trigger_config.target,
        )
        prompt = render_prompt_template(trigger_config.prompt_template, to_template_dict(prompt_context)) if trigger_config.prompt_template else ""
        record = dispatch_trigger_event(
            root,
            trigger=self._trigger_to_dict(trigger_config),
            event_type=event_type,
            payload=payload,
            metadata={**metadata, "event-id": delivery_id},
            context_id=context_id,
            prompt=prompt,
        )
        if record is None:
            raise RuntimeError("canonical trigger adapter rejected a matched event")
        _write_trigger_audit(root, trigger_id=trigger_config.trigger_id, event_type=event_type,
                             correlation_id=correlation_id, status="fired", job_id=record.work_id)

    def _trigger_to_dict(self, trigger: TriggerConfig) -> dict[str, Any]:
        values = {
            "contract-version": trigger.contract_version, "trigger-id": trigger.trigger_id,
            "kind": trigger.kind, "enabled": trigger.enabled, "event-pattern": trigger.event_pattern,
            "execution-profile-id": trigger.execution_profile_id, "workflow-profile": trigger.workflow_profile,
            "target": trigger.target, "prompt-template": trigger.prompt_template,
            "prompt-template-file": trigger.prompt_template_file, "filter": trigger.filter,
            "metadata-propagation": trigger.metadata_propagation,
        }
        return {key: value for key, value in values.items() if value is not None}


def _write_trigger_audit(
    project_root: Path, *, trigger_id: str | None, event_type: str | None,
    correlation_id: str | None, status: str, job_id: str | None = None,
    error_code: str | None = None, error_message: str | None = None,
    reason: str | None = None,
) -> None:
    record: dict[str, Any] = {
        "timestamp": now_iso_z(), "trigger_id": trigger_id or "", "event_type": event_type or "",
        "correlation_id": correlation_id, "status": status, "job_id": job_id,
        "error_code": error_code, "error_message": error_message,
    }
    if reason is not None:
        record["reason"] = reason
    try:
        append_operational_record(project_root / _TRIGGER_AUDIT_PATH, record)
    except AudiaGenticError:
        raise
    except Exception:  # noqa: BLE001 - audit must not break event delivery
        logger.error("Failed to write trigger audit", exc_info=True)


_observer_instance: EventObserver | None = None


def get_event_observer(project_root: Path) -> EventObserver:
    global _observer_instance
    if _observer_instance is None:
        _observer_instance = EventObserver()
    if not _observer_instance._subscribed:
        _observer_instance.initialize(project_root)
    return _observer_instance


def _initialize_for_component_lifecycle(project_root: Path, _payload: dict, _metadata: dict) -> None:
    try:
        get_event_observer(project_root)
    except Exception:  # noqa: BLE001 - lifecycle observer isolation boundary
        logger.error("Failed to initialize agent-jobs event observer", exc_info=True)


subscribe_component_lifecycle(
    "agent-jobs",
    on_installed=_initialize_for_component_lifecycle,
    on_enabled=_initialize_for_component_lifecycle,
    on_config_changed=_initialize_for_component_lifecycle,
)
