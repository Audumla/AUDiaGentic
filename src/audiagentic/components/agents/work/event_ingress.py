"""Foundation event-bus ingress for canonical Agent Work."""
from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from audiagentic.components.agents.configuration.configuration_api import AgentsConfigService
from audiagentic.foundation.event.event_bus import SubscriptionHandle, get_bus

from .contracts import AgentWorkRecord
from .event_failures import record_event_failure
from .service import get_work
from .work_api import submit_trigger_event

PromptBuilder = Callable[[Mapping[str, Any], str, Mapping[str, Any], Mapping[str, Any]], str]


def default_event_prompt(
    trigger: Mapping[str, Any],
    event_type: str,
    payload: Mapping[str, Any],
    metadata: Mapping[str, Any],
) -> str:
    """Build a deterministic prompt when a trigger has no custom builder."""
    configured = trigger.get("prompt") or trigger.get("prompt-template")
    if isinstance(configured, str) and configured:
        return configured
    return json.dumps(
        {"event-type": event_type, "payload": dict(payload), "metadata": dict(metadata)},
        sort_keys=True,
        default=str,
    )


class WorkEventIngress:
    """Subscribe configured event triggers and submit replay-safe Work records."""

    def __init__(
        self,
        project_root: Path,
        *,
        context_id: str,
        triggers: Sequence[Mapping[str, Any]],
        prompt_builder: PromptBuilder | None = None,
    ) -> None:
        self._project_root = project_root.resolve()
        self._context_id = context_id
        self._triggers = tuple(dict(trigger) for trigger in triggers)
        self._prompt_builder = prompt_builder or default_event_prompt
        self._handles: list[SubscriptionHandle] = []

    @classmethod
    def from_project_config(
        cls,
        project_root: Path,
        *,
        context_id: str,
        prompt_builder: PromptBuilder | None = None,
    ) -> WorkEventIngress:
        """Construct ingress from the canonical ``agents.yaml`` document."""
        triggers = AgentsConfigService().triggers(project_root)
        return cls(
            project_root,
            context_id=context_id,
            triggers=triggers,
            prompt_builder=prompt_builder,
        )

    def start(self) -> None:
        """Subscribe once for each usable trigger."""
        if self._handles:
            return
        bus = get_bus()
        for trigger in self._triggers:
            pattern = trigger.get("event-pattern", trigger.get("event_pattern"))
            if isinstance(pattern, str) and pattern:
                self._handles.append(bus.subscribe(pattern, self._handler(trigger)))

    def stop(self) -> None:
        """Remove all subscriptions; safe to call repeatedly."""
        bus = get_bus()
        for handle in self._handles:
            bus.unsubscribe(handle)
        self._handles.clear()

    def _handler(self, trigger: Mapping[str, Any]):
        def handle(event_type: str, payload: dict[str, Any], metadata: dict[str, Any]) -> None:
            try:
                self.submit(trigger, event_type, payload, metadata)
            except Exception as exc:  # noqa: BLE001 - bus subscriber isolation boundary
                record_event_failure(
                    self._project_root,
                    trigger_id=str(trigger.get("trigger-id", trigger.get("trigger_id", "event"))),
                    event_type=event_type,
                    correlation_id=str(metadata.get("correlation-id") or metadata.get("correlation_id") or ""),
                    error_code=getattr(exc, "code", "INT-AGW-EVENT-001"),
                )

        return handle

    def submit(
        self,
        trigger: Mapping[str, Any],
        event_type: str,
        payload: Mapping[str, Any],
        metadata: Mapping[str, Any] | None = None,
    ) -> AgentWorkRecord | None:
        """Evaluate one event and submit exactly one deterministic Work on match."""
        event_metadata = dict(metadata or {})
        prompt = self._prompt_builder(trigger, event_type, payload, event_metadata)
        result = submit_trigger_event(
            self._project_root,
            trigger=trigger,
            event_type=event_type,
            payload=payload,
            metadata=event_metadata,
            context_id=self._context_id,
            prompt=prompt,
        )
        if result is None:
            return None
        return get_work(self._project_root, result["work_id"])
