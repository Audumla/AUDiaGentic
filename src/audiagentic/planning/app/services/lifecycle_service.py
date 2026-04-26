from __future__ import annotations

from datetime import datetime, timezone

from ...fs.read import parse_markdown
from ...fs.write import dump_markdown


class LifecycleService:
    def __init__(self, api):
        self.api = api

    def state(
        self,
        id_: str,
        new_state: str,
        reason: str | None = None,
        actor: str | None = None,
        metadata: dict | None = None,
    ):
        item = self.api._find(id_)
        data, body = parse_markdown(item.path)
        wf_name = data.get("workflow")
        wf = self.api.config.workflow_for(item.kind, wf_name)
        old = data["state"]
        if new_state not in wf["values"]:
            raise ValueError(f"unknown state {new_state} for workflow")
        if new_state not in wf["transitions"].get(old, []):
            raise ValueError(f"invalid transition {old} -> {new_state}")
        data["state"] = new_state
        timestamp = datetime.now(timezone.utc).isoformat()
        event_payload = {"id": id_, "old_state": old, "new_state": new_state}
        if actor is not None:
            event_payload["actor"] = actor
        if reason is not None:
            event_payload["reason"] = reason
        _, action = self.api.config.lifecycle_action_for_transition(
            item.kind, old, new_state, wf_name
        )
        if action:
            self.apply_metadata(
                data,
                event_payload,
                action.get("metadata", {}),
                timestamp=timestamp,
                actor=actor,
                reason=reason,
            )
        dump_markdown(item.path, data, body)
        if action and action.get("event_suffix"):
            self.api.events.emit(f"{item.kind}.{action['event_suffix']}", event_payload)

        if action:
            self.cascade(id_, item.kind, action, actor, reason)

        event_metadata = {
            "subject": {"kind": item.kind, "id": id_},
            "triggered_by": "manual",
            "project_root": str(self.api.root.resolve()),
        }
        if metadata:
            event_metadata.update(metadata)

        mode = self.api.event_service.sync_delivery_mode()
        self.api._publish_event(
            "planning.item.state.changed",
            event_payload,
            event_metadata,
            mode=mode,
        )

        self.api.index()
        return self.api._find(id_)

    def apply_action(
        self,
        name: str,
        id_: str,
        reason: str | None = None,
        actor: str | None = None,
        metadata: dict | None = None,
    ):
        action = self.api.config.lifecycle_action(name)
        transition_to = action.get("transition_to")
        if not transition_to:
            raise ValueError(f"lifecycle action '{name}' has no transition_to state")
        return self.state(id_, transition_to, reason=reason, actor=actor, metadata=metadata)

    def apply_metadata(
        self,
        data: dict,
        event_payload: dict,
        metadata_rules: dict,
        *,
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
        for field, token in metadata_rules.items():
            value = values.get(token, token)
            data[field] = value
            event_payload[field] = value

    def cascade(
        self, id_: str, kind: str, action: dict, actor: str | None, reason: str | None
    ) -> None:
        cascade_rules = action.get("cascade", {}).get("by_kind", {}).get(kind, {})
        if not cascade_rules:
            return

        for item in self.api._scan():
            target_state = cascade_rules.get(item.kind)
            if not target_state:
                continue
            if self.api.config.state_in_set(
                item.kind, item.data.get("state"), "terminal", item.data.get("workflow")
            ):
                continue
            if not self.api.relationships.child_refs_parent(item, kind, id_):
                continue
            try:
                self.state(
                    item.data["id"],
                    target_state,
                    reason=reason or f"Cascaded from {id_}",
                    actor=actor,
                )
            except Exception:
                pass

    def is_terminal(self, id_: str) -> bool:
        try:
            item = self.api._find(id_)
            return self.api.config.state_in_set(
                item.kind, item.data.get("state"), "terminal", item.data.get("workflow")
            )
        except KeyError:
            return True

