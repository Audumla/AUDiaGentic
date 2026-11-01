from __future__ import annotations

from pathlib import Path

from audiagentic.components.agents.context.service import get_context
from audiagentic.components.agents.work.contracts import (
    AgentWorkRecord,
    AgentWorkState,
    WorkCommandReceipt,
    WorkInputMessage,
)
from audiagentic.components.agents.work.inputs import append_work_input
from audiagentic.components.agents.work.store import AgentWorkStore, command_error
from audiagentic.foundation.contracts.errors import AudiaGenticError


def submit_work(
    project_root: Path,
    context_id: str,
    message: WorkInputMessage,
    *,
    work_id: str | None = None,
    parent_work_id: str | None = None,
    activate: bool = True,
) -> AgentWorkRecord:
    context = get_context(project_root, context_id)
    if context.state.value != "open":
        raise ValueError("context is closed")
    store = AgentWorkStore()
    try:
        if parent_work_id is not None:
            parent = store.get(project_root, parent_work_id)
            if parent.context_id != context_id:
                raise ValueError("parent work belongs to a different context")
        work = store.create(
            project_root,
            context_id,
            work_id=work_id,
            parent_work_id=parent_work_id,
        )
    except FileExistsError:
        work = store.get(project_root, work_id)
        if work.context_id != context_id:
            raise ValueError("work ID belongs to a different context")
        if work.state in {
            AgentWorkState.COMPLETED,
            AgentWorkState.FAILED,
            AgentWorkState.CANCELLED,
            AgentWorkState.REJECTED,
        }:
            return work
    append_work_input(project_root, work.work_id, message)
    if not activate or work.state != AgentWorkState.SUBMITTED:
        return work
    return store.transition(project_root, work.work_id, AgentWorkState.ACTIVE, expected_revision=work.revision)


def get_work(project_root: Path, work_id: str) -> AgentWorkRecord:
    return AgentWorkStore().get(project_root, work_id)


def link_work_execution(project_root: Path, work_id: str, execution_id: str, *, expected_revision: int) -> AgentWorkRecord:
    return AgentWorkStore().link_execution(project_root, work_id, execution_id, expected_revision=expected_revision)


def list_work(project_root: Path) -> tuple[AgentWorkRecord, ...]:
    return AgentWorkStore().list(project_root)


def child_work(project_root: Path, parent_work_id: str) -> tuple[AgentWorkRecord, ...]:
    return tuple(work for work in list_work(project_root) if work.parent_work_id == parent_work_id)


def submit_child_work(
    project_root: Path,
    parent_work_id: str,
    message: WorkInputMessage,
    *,
    work_id: str | None = None,
    delegation_target_agent_id: str | None = None,
    delegation_timeout_seconds: float | None = None,
) -> AgentWorkRecord:
    parent = get_work(project_root, parent_work_id)
    depth = 0
    cursor = parent
    while cursor.parent_work_id is not None:
        depth += 1
        cursor = get_work(project_root, cursor.parent_work_id)
    if depth >= 8:
        raise ValueError("delegation depth limit exceeded")
    if delegation_target_agent_id is not None:
        message = WorkInputMessage(
            message.message_id,
            message.text,
            {
                **dict(message.inputs),
                "delegation-target-agent-id": delegation_target_agent_id,
                **({"delegation-timeout-seconds": delegation_timeout_seconds} if delegation_timeout_seconds is not None else {}),
            },
            message.created_at,
        )
    return submit_work(
        project_root,
        parent.context_id,
        message,
        work_id=work_id,
        parent_work_id=parent_work_id,
    )


def add_work_message(project_root: Path, work_id: str, message: WorkInputMessage) -> AgentWorkRecord:
    """Append one caller message without creating a second Work record."""
    work = get_work(project_root, work_id)
    if work.state in {AgentWorkState.COMPLETED, AgentWorkState.FAILED, AgentWorkState.CANCELLED, AgentWorkState.REJECTED}:
        raise ValueError("cannot add a message to terminal work")
    append_work_input(project_root, work_id, message)
    return work


def cancel_work(project_root: Path, work_id: str) -> AgentWorkRecord:
    work = get_work(project_root, work_id)
    if work.state in {AgentWorkState.COMPLETED, AgentWorkState.FAILED, AgentWorkState.CANCELLED, AgentWorkState.REJECTED}:
        return work
    result = AgentWorkStore().transition(project_root, work_id, AgentWorkState.CANCELLED, expected_revision=work.revision)
    for child in child_work(project_root, work_id):
        if child.state not in {AgentWorkState.COMPLETED, AgentWorkState.FAILED, AgentWorkState.CANCELLED, AgentWorkState.REJECTED}:
            cancel_work(project_root, child.work_id)
    return result


def read_work_output(project_root: Path, work_id: str) -> dict:
    """Project output from the gateway output owner; Work stores no output."""
    work = get_work(project_root, work_id)
    if not work.active_execution_id:
        return {"work_id": work_id, "execution_id": None, "events": []}
    from audiagentic.components.agents.gateway.output import read_request_output

    return read_request_output(project_root, work.active_execution_id)


def work_command_digest(text: str, inputs: dict, intent: dict | None = None) -> str:
    """Canonical digest of what a command asks for (never ``created_at``)."""
    import hashlib
    import json

    canonical = json.dumps({"text": text, "inputs": dict(inputs), "intent": dict(intent or {})},
                           sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def work_delivery_key(*, principal: str, subject: str | None, protocol: str, project_id: str, context_id: str,
                      target_generation: str | None, message_id: str) -> str:
    """The canonical delivery identity (SH60): who sent which protocol message to which Context and target."""
    import hashlib
    import json

    parts = {"principal": principal, "subject": subject, "protocol": protocol, "project": project_id,
             "context": context_id, "generation": target_generation, "message": message_id}
    if not all(isinstance(v, str) and v for k, v in parts.items() if k not in {"subject", "generation"}):
        raise command_error(163, "A delivery identity needs a principal, protocol, project, context and message id")
    return hashlib.sha256(json.dumps(parts, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def accept_work_command(
    project_root: Path,
    context_id: str,
    *,
    delivery_key: str,
    message: WorkInputMessage,
    intent: dict | None = None,
    work_id: str | None = None,
    parent_work_id: str | None = None,
    exclusive: bool = False,
) -> WorkCommandReceipt:
    """Commit one caller command to Work in a single atomic record write, then project its input.

    Creates the Work when ``work_id`` is new, continues it when it exists and is not terminal. The message is
    durable inside the record, so ``inputs.ndjson`` can be rebuilt after a crash (``append_work_input`` is
    idempotent per message id). Returns the original acceptance for an exact replay.
    """
    context = get_context(project_root, context_id)
    if context.state.value != "open":
        raise command_error(164, "The Context is closed and accepts no new Work", context_id=context_id)
    resolved_work_id = work_id or f"work_{delivery_key[:32]}"
    command = {
        "delivery_key": delivery_key,
        "digest": work_command_digest(message.text, dict(message.inputs), intent),
        "message": {"message_id": message.message_id, "text": message.text, "inputs": dict(message.inputs),
                    "created_at": message.created_at},
        "intent": dict(intent or {}),
        "accepted_at": message.created_at,
    }
    from audiagentic.components.agents.work.events import publish_work_event, topics

    try:
        receipt = AgentWorkStore().accept_command(project_root, context_id, work_id=resolved_work_id, command=command,
                                                  parent_work_id=parent_work_id, exclusive=exclusive)
    except AudiaGenticError as error:
        if error.code == "CON-AGW-161":
            known = AgentWorkStore().get(project_root, resolved_work_id)
            publish_work_event(topics.WORK_MESSAGE_CONFLICT_TOPIC, known.to_mapping(), delivery_key=delivery_key)
        raise
    publish_work_event(topics.WORK_MESSAGE_REPLAYED_TOPIC if receipt.replayed else topics.WORK_MESSAGE_ACCEPTED_TOPIC,
                       receipt.work.to_mapping(), delivery_key=delivery_key)
    stored = receipt.command["message"]
    append_work_input(project_root, receipt.work.work_id,
                      WorkInputMessage(stored["message_id"], stored["text"], stored["inputs"], stored["created_at"]))
    return receipt
