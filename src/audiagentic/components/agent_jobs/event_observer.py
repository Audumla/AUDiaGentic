"""Event observer for agent-jobs component (EDJ02).

Subscribes to configured event trigger patterns on the foundation event bus
and dispatches matching events through the gateway lifecycle.  Handler
failures are dead-lettered and never propagate to other subscribers.
"""
from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from audiagentic.components.agent_jobs.dead_letter import write_dead_letter
from audiagentic.components.agent_jobs.event_triggers import (
    TriggerConfig,
    load_event_triggers,
)
from audiagentic.components.agent_jobs.events import record_job_timeline_event
from audiagentic.components.agent_jobs import jobs_store as store
from audiagentic.components.agent_jobs.prompt_context import (
    build_prompt_context_from_event,
    to_template_dict,
)
from audiagentic.components.agent_jobs.prompt_launch import build_job_from_event
from audiagentic.components.agent_jobs.prompt_templates import render_prompt_template
from audiagentic.components.agent_jobs.state_machine import (
    is_terminal_state,
    transition_and_persist,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError, make_error_factory
from audiagentic.foundation.event.envelope import EventEnvelope
from audiagentic.foundation.event.event_bus import DeliveryMode, SubscriptionHandle, get_bus
from audiagentic.foundation.logging.context import (
    get_correlation_id as _get_ctx_correlation_id,
)
from audiagentic.foundation.logging.context import (
    new_correlation_id as _new_correlation_id,
)
from audiagentic.foundation.observability.operational_records import append_operational_record
from audiagentic.foundation.time import now_iso_z

logger = logging.getLogger(__name__)

_eob_error = make_error_factory("CON", "EOB", "event-observer-subscription")

_TRIGGER_AUDIT_PATH = Path(".audiagentic") / "runtime" / "agent-jobs" / "trigger-audit.ndjson"


class EventObserver:
    """Core event observer that subscribes to configured trigger patterns."""

    def __init__(self) -> None:
        self._subscribed: bool = False
        self._project_root: Path | None = None
        self._handles: list[SubscriptionHandle] = []
        self._triggers: list[TriggerConfig] = []

    # ------------------------------------------------------------------
    # Initialization / subscription
    # ------------------------------------------------------------------

    def initialize(self, project_root: Path) -> None:
        """Load trigger config and subscribe to enabled event patterns.

        Double-register (calling twice with the same or different roots) only
        subscribes once per pattern — the ``_subscribed`` flag guards against
        duplicate registration.
        """
        if self._subscribed:
            return

        self._project_root = project_root.resolve()
        try:
            self._triggers = load_event_triggers(self._project_root)
        except AudiaGenticError:
            raise
        except Exception as exc:  # noqa: BLE001 — external boundary
            logger.error(
                "Failed to load event triggers during observer initialization",
                exc_info=exc,
            )
            _write_trigger_audit(
                self._project_root,
                trigger_id=None,
                event_type=None,
                correlation_id=None,
                status="failed",
                job_id=None,
                error_code="IO-TRIG-001",
                error_message=str(exc),
            )
            return

        bus = get_bus()
        seen_patterns: set[str] = set()

        for trigger in self._triggers:
            if not trigger.event_pattern:
                continue
            pattern = trigger.event_pattern
            if pattern in seen_patterns:
                logger.warning(
                    "Duplicate event pattern %r; skipping second subscription",
                    pattern,
                )
                continue
            seen_patterns.add(pattern)

            try:
                handle = bus.subscribe(pattern, self._make_handler(trigger))
                self._handles.append(handle)
            except Exception:  # noqa: BLE001 — external boundary
                logger.error(
                    "Failed to subscribe to event pattern %r",
                    pattern,
                    exc_info=True,
                )
                _write_trigger_audit(
                    self._project_root,
                    trigger_id=trigger.trigger_id,
                    event_type=pattern,
                    correlation_id=None,
                    status="failed",
                    job_id=None,
                    error_code="CON-EOB-001",
                    error_message=f"failed to subscribe to event pattern {pattern!r}",
                )

        # -- EDJ05: subscribe to gateway outcome events ---------------------------
        _GW_OUTCOME_TOPICS = (
            "agents.llm.completed",
            "agents.llm.failed",
            "agents.llm.rejected",
            "agents.llm.cancelled",
        )
        for topic in _GW_OUTCOME_TOPICS:
            try:
                handle = bus.subscribe(topic, self._handle_gateway_outcome)
                self._handles.append(handle)
            except Exception:  # noqa: BLE001 — external boundary
                logger.error(
                    "Failed to subscribe to gateway outcome event %r",
                    topic,
                    exc_info=True,
                )

        self._subscribed = True

    # ------------------------------------------------------------------
    # Handler factory (closes over trigger config)
    # ------------------------------------------------------------------

    def _make_handler(
        self, trigger: TriggerConfig
    ) -> Callable[[str, dict[str, Any], dict[str, Any]], None]:
        """Return a bus handler bound to *trigger*."""

        def handler(event_type: str, payload: dict[str, Any], metadata: dict[str, Any]) -> None:
            self._on_trigger_match(trigger, event_type, payload, metadata)

        return handler

    # ------------------------------------------------------------------
    # Trigger match / dispatch
    # ------------------------------------------------------------------

    def _on_trigger_match(
        self,
        trigger_config: TriggerConfig,
        event_type: str,
        payload: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Process a matched event: job creation, template rendering, gateway dispatch, audit."""
        if self._project_root is None:
            logger.error("EventObserver not initialized; cannot dispatch event")
            return

        metadata = metadata or {}

        # -- resolve correlation_id --------------------------------------------------
        correlation_id = (
            metadata.get("correlation-id")
            or metadata.get("correlation_id")
        )
        if not correlation_id:
            correlation_id = _get_ctx_correlation_id() or _new_correlation_id()
            metadata["correlation_id"] = correlation_id

        # -- disabled trigger => suppressed audit ------------------------------------
        if not trigger_config.enabled:
            _write_trigger_audit(
                self._project_root,
                trigger_id=trigger_config.trigger_id,
                event_type=event_type,
                correlation_id=correlation_id,
                status="suppressed",
                job_id=None,
            )
            logger.info(
                "Trigger %s suppressed (disabled); event=%s corr=%s",
                trigger_config.trigger_id,
                event_type,
                correlation_id,
            )
            return

        try:
            self._dispatch(trigger_config, event_type, payload, metadata, correlation_id)
        except Exception as exc:  # noqa: BLE001 — subscriber isolation boundary
            logger.error(
                "Event observer handler failed for trigger %s",
                trigger_config.trigger_id,
                exc_info=True,
            )

            error_code = ""
            error_message = str(exc)
            if isinstance(exc, AudiaGenticError):
                error_code = exc.code

            # -- dead-letter -----------------------------------------------------------
            try:
                write_dead_letter(
                    self._project_root,
                    {
                        "event_type": event_type,
                        "payload_summary": str(payload)[:500] if payload else "",
                        "metadata": metadata,
                        "trigger_id": trigger_config.trigger_id,
                        "job_id": None,
                        "error_code": error_code or "INT-EVT-001",
                        "error_message": error_message,
                        "correlation_id": correlation_id,
                    },
                )
            except Exception:  # noqa: BLE001 — dead-letter must never raise
                logger.error(
                    "Dead-letter write failed for trigger %s",
                    trigger_config.trigger_id,
                    exc_info=True,
                )

            _write_trigger_audit(
                self._project_root,
                trigger_id=trigger_config.trigger_id,
                event_type=event_type,
                correlation_id=correlation_id,
                status="failed",
                job_id=None,
                error_code=error_code or "INT-EVT-001",
                error_message=error_message[:500] if error_message else None,
            )

    # ------------------------------------------------------------------
    # Dispatch pipeline: build job -> render prompt -> gateway -> audit --
    # ------------------------------------------------------------------

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

        # -- build envelope dict for build_job_from_event ----------------------------
        envelope_dict: dict[str, Any] = {
            "event-id": f"evt-{uuid.uuid4().hex[:12]}",
            "source-kind": metadata.get("source-component", ""),
            "occurred-at": now_iso_z(),
            "payload": payload,
            "metadata": metadata,
        }

        # -- build durable job record ------------------------------------------------
        trigger_dict = self._trigger_to_dict(trigger_config)
        job_record = build_job_from_event(
            root,
            event_type=event_type,
            trigger_config=trigger_dict,
            envelope=envelope_dict,
            prompt_body="",
        )

        # -- propagate correlation_id through metadata -------------------------------
        metadata["correlation_id"] = correlation_id

        # -- build prompt context (EDJ10) --------------------------------------------
        subject_data = metadata.get("subject")
        if not isinstance(subject_data, dict):
            subject_data = None

        envelope = EventEnvelope(
            type=event_type,
            payload=payload,
            metadata=metadata,
            source_component=metadata.get("source-component", "agent-jobs"),
            correlation_id=correlation_id,
            subject=subject_data,
        )

        agent_profile_id = trigger_config.agent_profile_id or ""
        provider_id = job_record.get("provider-id", "")
        model_id = job_record.get("model-id") or ""

        prompt_context = build_prompt_context_from_event(
            envelope=envelope,
            trigger_config={
                "trigger_id": trigger_config.trigger_id,
                "event_pattern": trigger_config.event_pattern,
                "kind": trigger_config.kind,
            },
            project_root=str(root),
            project_id=job_record.get("project-id", ""),
            job_id=job_record["job-id"],
            agent_profile_id=agent_profile_id,
            provider_id=provider_id,
            model_id=model_id,
            target=trigger_config.target,
        )

        # -- render prompt template --------------------------------------------------
        prompt_body = ""
        if trigger_config.prompt_template:
            template_values = to_template_dict(prompt_context)
            try:
                prompt_body = render_prompt_template(trigger_config.prompt_template, template_values)
            except Exception:  # noqa: BLE001 — template rendering is best-effort
                logger.warning(
                    "Prompt template rendering failed for trigger %s; using empty body",
                    trigger_config.trigger_id,
                    exc_info=True,
                )
                prompt_body = ""

        # -- EDJ04: state transitions before dispatch --------------------------------
        job_id = job_record["job-id"]
        transition_and_persist(root, job_id, "ready")
        transition_and_persist(root, job_id, "running")

        # -- dispatch to gateway (EDJ04) ---------------------------------------------
        gateway_metadata = dict(metadata)
        gateway_metadata["correlation_id"] = correlation_id
        gateway_metadata["job-id"] = job_id
        gateway_metadata["subject"] = {"kind": "job", "id": job_id}

        get_bus().publish(
            "agents.llm.gateway.requested",
            {
                "project-root": str(root),
                "prompt-body": prompt_body,
                "agent-profile-id": trigger_config.agent_profile_id,
                "fallback-profile-ids": None,
                "source": f"event-trigger:{trigger_config.trigger_id}",
            },
            metadata=gateway_metadata,
            mode=DeliveryMode.SYNC,
        )

        # -- write fired audit entry -------------------------------------------------
        _write_trigger_audit(
            root,
            trigger_id=trigger_config.trigger_id,
            event_type=event_type,
            correlation_id=correlation_id,
            status="fired",
            job_id=job_record["job-id"],
        )

        logger.info(
            "Trigger %s fired; event=%s corr=%s job=%s",
            trigger_config.trigger_id,
            event_type,
            correlation_id,
            job_record["job-id"],
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # EDJ05: gateway outcome handler
    # ------------------------------------------------------------------

    GW_OUTCOME_MAP: dict[str, str] = {
        "agents.llm.completed": "completed",
        "agents.llm.failed": "failed",
        "agents.llm.rejected": "failed",
        "agents.llm.cancelled": "cancelled",
    }

    def _handle_gateway_outcome(
        self,
        event_type: str,
        payload: dict[str, Any],
        metadata: dict[str, Any],
    ) -> None:
        """Handle gateway lifecycle outcome events and propagate to job state (EDJ05)."""
        root = self._project_root
        if root is None:
            return

        try:
            target_state = self.GW_OUTCOME_MAP.get(event_type)
            if target_state is None:
                logger.warning("unexpected gateway outcome event type %r", event_type)
                return

            job_id = metadata.get("job-id") or payload.get("job-id")
            if not job_id:
                logger.info(
                    "gateway outcome %s missing job-id; ignoring",
                    event_type,
                )
                return

            request_id = payload.get("request-id") or payload.get("packet-id")

            try:
                record = store.read_job_record(root, job_id)
            except AudiaGenticError:
                logger.info(
                    "gateway outcome %s for unknown job %s; ignoring",
                    event_type,
                    job_id,
                )
                return

            current_state = record.get("state")

            if is_terminal_state(current_state):
                logger.info(
                    "gateway outcome %s for terminal job %s (state=%s); ignoring",
                    event_type,
                    job_id,
                    current_state,
                )
                return

            # -- capture request-id from first lifecycle event ----------------------
            if request_id:
                artifacts = record.get("artifacts") or []
                has_request_artifact = any(
                    a.get("kind") == "gateway-request" for a in artifacts
                )
                if not has_request_artifact:
                    append_gateway_artifact(root, job_id, request_id)

            # -- awaiting-approval: out-of-band; log but do NOT transition ----------
            if current_state == "awaiting-approval":
                logger.warning(
                    "gateway outcome %s arrived while job %s is awaiting-approval; "
                    "out-of-band — logging without state transition",
                    event_type,
                    job_id,
                )
                record_job_timeline_event(
                    root,
                    job_id,
                    "job.gateway-outcome-received",
                    state=current_state,
                    attributes={
                        "event_type": event_type,
                        "request-id": request_id,
                        "reason": "out-of-band-while-awaiting-approval",
                    },
                )
                return

            # -- persist outcome summary in timeline ---------------------------------
            correlation_id = metadata.get("correlation_id") or metadata.get("correlation-id", "")
            error_info = payload.get("error") or payload.get("exception")
            outcome_attrs: dict[str, Any] = {
                "event_type": event_type,
                "target-state": target_state,
            }
            if request_id:
                outcome_attrs["request-id"] = request_id
            provider_id = payload.get("provider-id") or record.get("provider-id")
            model_id = payload.get("model-id")
            attempt_count = payload.get("attempt_count")
            if provider_id:
                outcome_attrs["provider-id"] = provider_id
            if model_id:
                outcome_attrs["model-id"] = model_id
            if error_info is not None:
                error_str = error_info if isinstance(error_info, str) else str(error_info)
                outcome_attrs["error"] = error_str[:500]
            if attempt_count is not None:
                outcome_attrs["attempt_count"] = attempt_count

            # -- transition ---------------------------------------------------------
            transition_and_persist(
                root,
                job_id,
                target_state,
                correlation_id=correlation_id,
            )

            record_job_timeline_event(
                root,
                job_id,
                "job.state-propagated",
                state=target_state,
                attributes=outcome_attrs,
                correlation_id=correlation_id,
            )

            logger.info(
                "gateway outcome %s propagated for job %s: %s -> %s",
                event_type,
                job_id,
                current_state,
                target_state,
            )

        except AudiaGenticError:
            raise
        except Exception as exc:  # noqa: BLE001 — subscriber isolation boundary
            logger.error(
                "Gateway outcome handler failed for event %s",
                event_type,
                exc_info=True,
            )
            try:
                write_dead_letter(
                    root,
                    {
                        "event_type": event_type,
                        "payload_summary": str(payload)[:500],
                        "metadata": metadata,
                        "trigger_id": "",
                        "job_id": metadata.get("job-id"),
                        "error_code": "INT-GW-001",
                        "error_message": str(exc)[:500],
                        "correlation_id": metadata.get("correlation_id") or "",
                    },
                )
            except Exception:  # noqa: BLE001 — dead-letter must never raise
                logger.error(
                    "Dead-letter write failed for gateway outcome handler",
                    exc_info=True,
                )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _trigger_to_dict(self, tc: TriggerConfig) -> dict[str, Any]:
        d: dict[str, Any] = {
            "contract-version": tc.contract_version,
            "trigger-id": tc.trigger_id,
            "kind": tc.kind,
            "enabled": tc.enabled,
            "event-pattern": tc.event_pattern,
            "agent-profile-id": tc.agent_profile_id,
            "workflow-profile": tc.workflow_profile,
            "target": tc.target,
            "prompt-template": tc.prompt_template,
            "prompt-template-file": tc.prompt_template_file,
            "metadata-propagation": tc.metadata_propagation,
        }
        return {k: v for k, v in d.items() if v is not None}


# ---------------------------------------------------------------------------
# EDJ05: gateway artifact helper
# ---------------------------------------------------------------------------


def append_gateway_artifact(project_root: Path, job_id: str, request_id: str) -> None:
    """Append a gateway-request artifact to the job record."""
    record = store.read_job_record(project_root, job_id)
    record.setdefault("artifacts", []).append(
        {
            "kind": "gateway-request",
            "request-id": request_id,
        }
    )
    store.write_job_record(project_root, record)


def _write_trigger_audit(
    project_root: Path,
    *,
    trigger_id: str | None,
    event_type: str | None,
    correlation_id: str | None,
    status: str,
    job_id: str | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
) -> None:
    """Append a single trigger-audit ndjson entry (EDJ14 shape)."""
    record = {
        "timestamp": now_iso_z(),
        "trigger_id": trigger_id or "",
        "event_type": event_type or "",
        "correlation_id": correlation_id,
        "status": status,
        "job_id": job_id,
        "error_code": error_code,
        "error_message": error_message,
    }
    try:
        append_operational_record(
            project_root / _TRIGGER_AUDIT_PATH,
            record,
        )
    except AudiaGenticError:
        raise
    except Exception:  # noqa: BLE001 — external boundary (disk I/O)
        logger.error(
            "Failed to write trigger-audit entry",
            exc_info=True,
        )


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_observer_instance: EventObserver | None = None


def get_event_observer(project_root: Path) -> EventObserver:
    """Return the singleton EventObserver (lazy-initialized on first call).

    Repeated calls with the same project root return the same instance.
    Calling again after initialization is a no-op for subscription
    (the ``_subscribed`` flag ensures idempotent registration).
    """
    global _observer_instance
    if _observer_instance is None:
        _observer_instance = EventObserver()
    if not _observer_instance._subscribed and project_root is not None:
        _observer_instance.initialize(project_root)
    return _observer_instance
