"""Config-driven state transition engine.

Validates transitions against workflows, applies lifecycle action metadata,
emits events, and triggers configured cascades. The engine is generic —
it never reads or writes item files directly; the host's WorkflowContext
provides lookup/save/event-publish.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from audiagentic.foundation.contracts.errors import AudiaGenticError, make_error

from .interfaces import ItemView, WorkflowContext
from .util import extract_ref_ids

logger = logging.getLogger(__name__)

DEFAULT_STATE_CHANGE_EVENT = "workflow.item.state.changed"


def _state_error(code_number: int, message: str, **details: Any) -> AudiaGenticError:
    return make_error(
        prefix="VAL",
        component="WFSM",
        number=code_number,
        kind="workflow",
        message=message,
        details=details,
    )


class StateMachine:
    def __init__(self, ctx: WorkflowContext):
        self.ctx = ctx

    def state(
        self,
        id_: str,
        new_state: str,
        reason: str | None = None,
        actor: str | None = None,
        metadata: dict[str, Any] | None = None,
    ):
        item = self.ctx._find(id_)
        data = item.data
        wf_name = data.get("workflow")
        wf = self.ctx.config.workflow_for(item.kind, wf_name)
        old = data.get("state", self.ctx.config.initial_state(item.kind, wf_name))

        if new_state not in wf["values"]:
            raise _state_error(1, f"unknown state {new_state} for workflow", state=new_state)
        if new_state not in wf["transitions"].get(old, []):
            raise _state_error(2, f"invalid transition {old} -> {new_state}", old_state=old, new_state=new_state)

        data["state"] = new_state
        timestamp = datetime.now(timezone.utc).isoformat()
        event_payload: dict[str, Any] = {"id": id_, "old_state": old, "new_state": new_state}
        if actor is not None:
            event_payload["actor"] = actor
        if reason is not None:
            event_payload["reason"] = reason

        _, action = self.ctx.config.lifecycle_action_for_transition(
            item.kind, old, new_state, wf_name
        )
        if action:
            self._apply_metadata(
                data, event_payload, action.get("metadata", {}), timestamp, actor, reason
            )

        self.ctx.save(item)

        if action and action.get("event_suffix"):
            self.ctx._publish_event(f"{item.kind}.{action['event_suffix']}", event_payload, None)

        if action:
            self._cascade(id_, item.kind, action, actor, reason, metadata=metadata)

        event_metadata = {
            "subject": {"kind": item.kind, "id": id_},
            "triggered_by": "manual",
            "project_root": str(self.ctx.root.resolve()),
            **(metadata or {}),
        }

        self.ctx._publish_event(
            self._state_change_event_type(), event_payload, event_metadata, mode="sync"
        )

        self.ctx.index()
        return self.ctx._find(id_)

    def _state_change_event_type(self) -> str:
        configured = getattr(self.ctx.config, "state_change_event_type", None)
        if configured is None:
            return DEFAULT_STATE_CHANGE_EVENT
        event_type = configured()
        if not isinstance(event_type, str) or not event_type:
            raise _state_error(3, "state_change_event_type must return a non-empty string")
        return event_type

    def apply_action(
        self,
        name: str,
        id_: str,
        reason: str | None = None,
        actor: str | None = None,
        metadata: dict[str, Any] | None = None,
    ):
        action = self.ctx.config.lifecycle_action(name)
        transition_to = action.get("transition_to")
        if not transition_to:
            raise _state_error(4, f"lifecycle action '{name}' has no transition_to state", action=name)
        return self.state(id_, transition_to, reason=reason, actor=actor, metadata=metadata)

    def is_terminal(self, id_: str) -> bool:
        try:
            item = self.ctx._find(id_)
        except KeyError:
            return True
        return self.ctx.config.state_in_set(
            item.kind, item.data.get("state"), "terminal", item.data.get("workflow")
        )

    def _apply_metadata(
        self,
        data: dict[str, Any],
        event_payload: dict[str, Any],
        rules: dict[str, str],
        timestamp: str,
        actor: str | None,
        reason: str | None,
    ) -> None:
        values = {
            "now": timestamp,
            "actor": actor,
            "actor_or_system": actor or "system",
            "reason": reason,
            "reason_or_empty": reason or "",
            "null": None,
        }
        for field, token in rules.items():
            value = values.get(token, token)
            data[field] = value
            event_payload[field] = value

    def _cascade(
        self,
        id_: str,
        kind: str,
        action: dict[str, Any],
        actor: str | None,
        reason: str | None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        rules = action.get("cascade", {}).get("by_kind", {}).get(kind, {})
        if not rules:
            return
        depth = (metadata or {}).get("propagation_depth", 0)
        cascade_metadata = dict(metadata or {})
        cascade_metadata["propagation_depth"] = depth + 1
        source = self.ctx._find(id_)
        for target_kind, target in rules.items():
            for item in self._cascade_targets(source, kind, target_kind):
                if self.is_terminal(item.data["id"]):
                    continue
                try:
                    self.state(
                        item.data["id"],
                        target,
                        reason=reason or f"Cascaded from {id_}",
                        actor=actor,
                        metadata=cascade_metadata,
                    )
                except AudiaGenticError:
                    logger.warning(
                        "cascade failed %s -> %s",
                        item.data.get("id"),
                        target,
                        exc_info=True,
                    )

    def _cascade_targets(
        self, source: ItemView, source_kind: str, target_kind: str
    ) -> list[ItemView]:
        """Find target-kind items directly related to source via configured refs."""
        source_id = source.data.get("id")
        if not isinstance(source_id, str) or not source_id:
            return []

        targets: list[ItemView] = []
        seen: set[str] = set()

        def add(item: ItemView | None) -> None:
            if item is None or item.kind != target_kind:
                return
            item_id = item.data.get("id")
            if not isinstance(item_id, str) or item_id in seen:
                return
            seen.add(item_id)
            targets.append(item)

        for field in self.ctx.config.reference_fields(source_kind):
            field_targets = self.ctx.config.reference_field_targets(field)
            if target_kind not in field_targets:
                continue
            for item_id in extract_ref_ids(source.data.get(field)):
                add(self.ctx.lookup(item_id))

        for item in self.ctx._scan():
            if item.kind != target_kind:
                continue
            for field in self.ctx.config.reference_fields(target_kind):
                field_targets = self.ctx.config.reference_field_targets(field)
                if source_kind not in field_targets:
                    continue
                if source_id in extract_ref_ids(item.data.get(field)):
                    add(item)
                    break

        return targets
