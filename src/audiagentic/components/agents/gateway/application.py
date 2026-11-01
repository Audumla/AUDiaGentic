"""Gateway application/control-plane boundary for the in-process backend.

This module is deliberately framework-neutral.  SH04 service transports will
host this application; SH03 inbound adapters reach it only through the client.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from audiagentic.components.agents.gateway.admission.context import (
    ComponentContextReader,
    empty_component_context,
)


class GatewayApplication(Protocol):
    """Operations owned by the gateway control plane."""

    def submit_execution_request(self, project_root: Path, **kwargs: Any) -> dict[str, Any]: ...
    def get_execution_request(self, project_root: Path, request_id: str, *, include_response: bool = False) -> dict[str, Any]: ...
    def get_execution_diagnostics(self, project_root: Path, request_id: str, *, limit: int = 25) -> dict[str, Any]: ...
    def recover_execution_request(self, project_root: Path, request_id: str, **kwargs: Any) -> dict[str, Any]: ...
    def get_execution_observations(self, project_root: Path, request_id: str, **kwargs: Any) -> dict[str, Any]: ...
    def get_execution_evidence(self, project_root: Path, request_id: str, **kwargs: Any) -> dict[str, Any]: ...
    def replay_execution_observations(self, project_root: Path, request_id: str) -> dict[str, Any]: ...

    def get_execution_response_payload(self, project_root: Path, request_id: str) -> dict[str, Any]: ...
    def get_execution_response(self, project_root: Path, request_id: str) -> str: ...
    def get_execution_failure_response(self, project_root: Path, request_id: str) -> str: ...
    def focus_execution_chat(self, project_root: Path, request_id: str) -> dict[str, Any]: ...
    def focus_execution_session(self, project_root: Path, session_id: str) -> dict[str, Any]: ...
    def complete_execution_from_provider(self, project_root: Path, request_id: str) -> dict[str, Any]: ...
    def wait_execution_request(
        self,
        project_root: Path,
        request_id: str,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]: ...
    def cancel_execution_request(self, project_root: Path, request_id: str) -> dict[str, Any]: ...
    def run_execution_request(self, project_root: Path, **kwargs: Any) -> dict[str, Any]: ...
    def request_runtime_status(self, project_root: Path, request_id: str) -> dict[str, Any]: ...
    def list_execution_requests(
        self, project_root: Path, **kwargs: Any
    ) -> list[dict[str, Any]]: ...
    def gateway_overview(self, project_root: Path) -> dict[str, Any]: ...
    def list_execution_sessions(
        self, project_root: Path, **kwargs: Any
    ) -> list[dict[str, Any]]: ...
    def close_execution_session(self, project_root: Path, session_id: str) -> dict[str, Any]: ...
    def purge_execution_session(self, project_root: Path, session_id: str) -> dict[str, Any]: ...
    def purge_execution_sessions(
        self,
        project_root: Path,
        *,
        dry_run: bool = True,
        session_ids: list[str] | None = None,
    ) -> dict[str, Any]: ...
    def control_execution_session(
        self, project_root: Path, session_id: str, **kwargs: Any
    ) -> dict[str, Any]: ...
    def resume_execution_session(
        self, project_root: Path, source_session_id: str, **kwargs: Any
    ) -> dict[str, Any]: ...
    def open_agent_context(self, project_root: Path, agent_id: str, title: str | None = None) -> dict[str, Any]: ...
    def get_agent_context(self, project_root: Path, context_id: str) -> dict[str, Any]: ...
    def list_agent_contexts(self, project_root: Path) -> list[dict[str, Any]]: ...
    def close_agent_context(self, project_root: Path, context_id: str) -> dict[str, Any]: ...
    def submit_agent_work(self, project_root: Path, context_id: str, message: dict[str, Any], **kwargs: Any) -> dict[str, Any]: ...
    def accept_agent_work_message(self, project_root: Path, context_id: str, message: dict[str, Any], *, delivery_identity: dict[str, Any], work_id: str | None = None, intent: dict[str, Any] | None = None, exclusive: bool = False) -> dict[str, Any]: ...
    def dispatch_agent_work_commands(self, project_root: Path, work_id: str) -> dict[str, Any]: ...
    def wait_agent_work(self, project_root: Path, work_id: str, timeout_seconds: float | None = None) -> dict[str, Any]: ...
    def get_agent_work(self, project_root: Path, work_id: str) -> dict[str, Any]: ...
    def list_agent_work(self, project_root: Path) -> list[dict[str, Any]]: ...
    def add_agent_work_message(self, project_root: Path, work_id: str, message: dict[str, Any]) -> dict[str, Any]: ...
    def cancel_agent_work(self, project_root: Path, work_id: str) -> dict[str, Any]: ...
    def read_agent_work_output(self, project_root: Path, work_id: str) -> dict[str, Any]: ...


class InProcessGatewayApplication:
    """The existing API implementation presented as one control-plane owner."""

    def __init__(
        self,
        *,
        component_context_reader: ComponentContextReader = empty_component_context,
    ) -> None:
        self._component_context_reader = component_context_reader

    @staticmethod
    def _api() -> Any:
        from audiagentic.components.agents.gateway import api as agents_gateway_api

        return agents_gateway_api

    def submit_execution_request(self, project_root: Path, **kwargs: Any) -> dict[str, Any]:
        return self._api().submit_execution_request(
            project_root,
            component_context_reader=self._component_context_reader,
            **kwargs,
        )

    def get_execution_request(self, project_root: Path, request_id: str, *, include_response: bool = False) -> dict[str, Any]:
        return self._api().get_execution_request(project_root, request_id, include_response=include_response)

    def get_execution_diagnostics(self, project_root: Path, request_id: str, *, limit: int = 25) -> dict[str, Any]:
        return self._api().get_execution_diagnostics(project_root, request_id, limit=limit)

    def get_execution_observations(self, project_root: Path, request_id: str, **kwargs: Any) -> dict[str, Any]:
        return self._api().get_execution_observations(project_root, request_id, **kwargs)

    def get_execution_evidence(self, project_root: Path, request_id: str, **kwargs: Any) -> dict[str, Any]:
        return self._api().get_execution_evidence(project_root, request_id, **kwargs)
    def replay_execution_observations(self, project_root: Path, request_id: str) -> dict[str, Any]:
        return self._api().replay_execution_observations(project_root, request_id)

    def recover_execution_request(self, project_root: Path, request_id: str, **kwargs: Any) -> dict[str, Any]:
        return self._api().recover_execution_request(project_root, request_id, **kwargs)

    def get_execution_response_payload(self, project_root: Path, request_id: str) -> dict[str, Any]:
        return self._api().get_execution_response_payload(project_root, request_id)

    def get_execution_response(self, project_root: Path, request_id: str) -> str:
        return self._api().get_execution_response(project_root, request_id)

    def get_execution_failure_response(self, project_root: Path, request_id: str) -> str:
        return self._api().get_execution_failure_response(project_root, request_id)

    def focus_execution_chat(self, project_root: Path, request_id: str) -> dict[str, Any]:
        return self._api().focus_execution_chat(project_root, request_id)

    def focus_execution_session(self, project_root: Path, session_id: str) -> dict[str, Any]:
        return self._api().focus_execution_session(project_root, session_id)

    def complete_execution_from_provider(self, project_root: Path, request_id: str) -> dict[str, Any]:
        return self._api().complete_execution_from_provider(project_root, request_id)

    def wait_execution_request(
        self,
        project_root: Path,
        request_id: str,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        return self._api().wait_execution_request(project_root, request_id, timeout_seconds)

    def cancel_execution_request(self, project_root: Path, request_id: str) -> dict[str, Any]:
        return self._api().cancel_execution_request(project_root, request_id)

    def request_runtime_status(self, project_root: Path, request_id: str) -> dict[str, Any]:
        return self._api().request_runtime_status(project_root, request_id)

    def run_execution_request(self, project_root: Path, **kwargs: Any) -> dict[str, Any]:
        return self._api().run_execution_request(
            project_root,
            component_context_reader=self._component_context_reader,
            **kwargs,
        )

    def list_execution_requests(self, project_root: Path, **kwargs: Any) -> list[dict[str, Any]]:
        return self._api().list_execution_requests(project_root, **kwargs)

    def gateway_overview(self, project_root: Path) -> dict[str, Any]:
        return self._api().gateway_overview(project_root)

    def list_execution_sessions(self, project_root: Path, **kwargs: Any) -> list[dict[str, Any]]:
        return self._api().list_execution_sessions(project_root, **kwargs)

    def close_execution_session(self, project_root: Path, session_id: str) -> dict[str, Any]:
        return self._api().close_execution_session(project_root, session_id)

    def purge_execution_session(self, project_root: Path, session_id: str) -> dict[str, Any]:
        return self._api().purge_execution_session(project_root, session_id)

    def purge_execution_sessions(
        self,
        project_root: Path,
        *,
        dry_run: bool = True,
        session_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        return self._api().purge_execution_sessions(
            project_root, dry_run=dry_run, session_ids=session_ids
        )

    def control_execution_session(
        self, project_root: Path, session_id: str, **kwargs: Any
    ) -> dict[str, Any]:
        return self._api().control_execution_session(project_root, session_id, **kwargs)

    def resume_execution_session(
        self, project_root: Path, source_session_id: str, **kwargs: Any
    ) -> dict[str, Any]:
        return self._api().resume_execution_session(project_root, source_session_id, **kwargs)

    def open_agent_context(self, project_root: Path, agent_id: str, title: str | None = None) -> dict[str, Any]:
        from audiagentic.components.agents.context.service import open_context
        return open_context(project_root, agent_id, title).to_mapping()

    def get_agent_context(self, project_root: Path, context_id: str) -> dict[str, Any]:
        from audiagentic.components.agents.context.service import get_context
        return get_context(project_root, context_id).to_mapping()

    def list_agent_contexts(self, project_root: Path) -> list[dict[str, Any]]:
        from audiagentic.components.agents.context.service import list_contexts
        return [record.to_mapping() for record in list_contexts(project_root)]

    def close_agent_context(self, project_root: Path, context_id: str) -> dict[str, Any]:
        from audiagentic.components.agents.context.service import close_context
        return close_context(project_root, context_id).to_mapping()

    def submit_agent_work(self, project_root: Path, context_id: str, message: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        from audiagentic.components.agents.context.service import get_context
        from audiagentic.components.agents.work.contracts import WorkInputMessage
        from audiagentic.components.agents.work.ingress import deterministic_work_id
        from audiagentic.components.agents.work.service import link_work_execution, submit_work

        requested_work_id = kwargs.pop("work_id", None)
        work_id = requested_work_id or deterministic_work_id(
            source="work-message",
            delivery_id=f"{context_id}:{message['message_id']}",
        )
        work = submit_work(
            project_root,
            context_id,
            WorkInputMessage(**message),
            activate=False,
            work_id=work_id,
            **kwargs,
        )
        if work.active_execution_id:
            if work.state.value == "submitted":
                from audiagentic.components.agents.work.contracts import AgentWorkState
                from audiagentic.components.agents.work.store import AgentWorkStore
                work = AgentWorkStore().transition(
                    project_root,
                    work.work_id,
                    AgentWorkState.ACTIVE,
                    expected_revision=work.revision,
                )
            return work.to_mapping()
        context = get_context(project_root, context_id)
        execution = self.submit_execution_request(
            project_root,
            execution_profile_id=context.composition.execution_profile_id,
            prompt_body=message["text"],
            metadata={
                "context-id": context_id,
                "work-id": work.work_id,
                "message-id": message["message_id"],
                "idempotency_key": f"agent-work:{work.work_id}:message:{message['message_id']}",
                "agent-config-fingerprint": context.composition.fingerprint,
            },
        )
        linked = link_work_execution(
            project_root,
            work.work_id,
            execution["request-id"],
            expected_revision=work.revision,
        )
        from audiagentic.components.agents.work.contracts import AgentWorkState
        from audiagentic.components.agents.work.store import AgentWorkStore
        return AgentWorkStore().transition(
            project_root,
            work.work_id,
            AgentWorkState.ACTIVE,
            expected_revision=linked.revision,
        ).to_mapping()

    def accept_agent_work_message(
        self, project_root: Path, context_id: str, message: dict[str, Any], *, delivery_identity: dict[str, Any],
        work_id: str | None = None, intent: dict[str, Any] | None = None, exclusive: bool = False,
    ) -> dict[str, Any]:
        """Accept one caller command (create or continue Work) atomically, then dispatch it idempotently.

        ``delivery_identity`` is assembled by trusted ingress (principal, protocol, project id, ...); the
        message is ``{message_id, text, inputs?}``. A replay returns the original acceptance and never
        admits a second execution.
        """
        from audiagentic.components.agents.work.contracts import WorkInputMessage
        from audiagentic.components.agents.work.service import (
            accept_work_command,
            work_delivery_key,
        )

        key = work_delivery_key(context_id=context_id, message_id=str(message.get("message_id") or ""),
                                **{k: delivery_identity.get(k) for k in
                                   ("principal", "subject", "protocol", "project_id", "target_generation")})
        stamped = WorkInputMessage(str(message["message_id"]), str(message["text"]), dict(message.get("inputs") or {}),
                                   message.get("created_at") or _now_iso())
        receipt = accept_work_command(project_root, context_id, delivery_key=key, message=stamped, intent=intent,
                                      work_id=work_id, exclusive=exclusive)
        work = self.dispatch_agent_work_commands(project_root, receipt.work.work_id)
        return {**work, "delivery_key": key, "replayed": receipt.replayed}

    def dispatch_agent_work_commands(self, project_root: Path, work_id: str) -> dict[str, Any]:
        """Admit every accepted command that has no gateway request yet, oldest first (crash repair).

        Each command admits under its own stable idempotency key, so a crash between admission and the link
        re-admits to the same request. Nothing is rebuilt from ``latest_work_input``.
        """
        from audiagentic.components.agents.context.service import get_context
        from audiagentic.components.agents.work.contracts import AgentWorkState
        from audiagentic.components.agents.work.service import get_work
        from audiagentic.components.agents.work.store import AgentWorkStore

        store = AgentWorkStore()
        work = get_work(project_root, work_id)
        context = get_context(project_root, work.context_id)
        for command in work.commands:
            if command.get("execution_id"):
                continue
            message = command["message"]
            execution = self.submit_execution_request(
                project_root,
                execution_profile_id=context.composition.execution_profile_id,
                prompt_body=message["text"],
                metadata={
                    "context-id": work.context_id,
                    "work-id": work.work_id,
                    "message-id": message["message_id"],
                    "idempotency_key": f"agent-work:{work.work_id}:command:{command['delivery_key']}",
                    "agent-config-fingerprint": context.composition.fingerprint,
                },
            )
            work = store.link_command_execution(project_root, work.work_id, command["delivery_key"],
                                                execution["request-id"])
            from audiagentic.components.agents.work.events import publish_work_event, topics

            publish_work_event(topics.WORK_EXECUTION_LINKED_TOPIC, work.to_mapping(),
                               delivery_key=command["delivery_key"], execution_id=execution["request-id"])
        if work.state is AgentWorkState.SUBMITTED and work.active_execution_id:
            work = store.transition(project_root, work.work_id, AgentWorkState.ACTIVE, expected_revision=work.revision)
        return work.to_mapping()

    def wait_agent_work(self, project_root: Path, work_id: str, timeout_seconds: float | None = None) -> dict[str, Any]:
        """Wait for the newest command's gateway request, then project its state onto Work.

        Waits through the existing request wait, holding no Work lock and no store lock. A timeout returns the
        non-terminal state (``wait-outcome: timeout``); success is never inferred.
        """
        from audiagentic.components.agents.work.reconcile import reconcile_work
        from audiagentic.components.agents.work.service import get_work

        bound = _WAIT_MAX_SECONDS if timeout_seconds is None else max(0.0, min(float(timeout_seconds), _WAIT_MAX_SECONDS))
        work = get_work(project_root, work_id)
        execution_id = work.active_execution_id
        if not execution_id:
            return {"work": work.to_mapping(), "execution-id": None, "wait-outcome": "no-execution", "state": None}
        waited = self.wait_execution_request(project_root, execution_id, bound)
        outcome = "timeout" if waited.get("wait-outcome") == "timeout" else "terminal"
        state = (waited.get("status") or {}).get("state") if outcome == "timeout" else waited.get("state")
        if state:
            work = reconcile_work(project_root, get_work(project_root, work_id), execution_state=str(state))
        return {"work": work.to_mapping(), "execution-id": execution_id, "wait-outcome": outcome, "state": state}

    def submit_agent_work_child(self, project_root: Path, parent_work_id: str, message: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        from audiagentic.components.agents.work.service import get_work
        parent = get_work(project_root, parent_work_id)
        return self.submit_agent_work(
            project_root,
            parent.context_id,
            message,
            work_id=kwargs.get("work_id"),
            parent_work_id=parent_work_id,
        )

    def get_agent_work(self, project_root: Path, work_id: str) -> dict[str, Any]:
        from audiagentic.components.agents.work.service import get_work
        return get_work(project_root, work_id).to_mapping()

    def list_agent_work(self, project_root: Path) -> list[dict[str, Any]]:
        from audiagentic.components.agents.work.service import list_work
        return [record.to_mapping() for record in list_work(project_root)]

    def add_agent_work_message(self, project_root: Path, work_id: str, message: dict[str, Any]) -> dict[str, Any]:
        from audiagentic.components.agents.work.contracts import WorkInputMessage
        from audiagentic.components.agents.work.service import add_work_message
        return add_work_message(project_root, work_id, WorkInputMessage(**message)).to_mapping()

    def cancel_agent_work(self, project_root: Path, work_id: str) -> dict[str, Any]:
        from audiagentic.components.agents.work.service import cancel_work, child_work, get_work

        work = get_work(project_root, work_id)
        to_cancel = (work, *child_work(project_root, work_id))
        for candidate in to_cancel:
            if candidate.active_execution_id:
                self.cancel_execution_request(project_root, candidate.active_execution_id)
        cancel_work(project_root, work_id)
        for candidate in to_cancel[1:]:
            cancel_work(project_root, candidate.work_id)
        return get_work(project_root, work_id).to_mapping()

    def read_agent_work_output(self, project_root: Path, work_id: str) -> dict[str, Any]:
        from audiagentic.components.agents.work.service import read_work_output
        return read_work_output(project_root, work_id)


_APPLICATION: GatewayApplication = InProcessGatewayApplication()


def get_gateway_application() -> GatewayApplication:
    """Return this process's sole gateway control-plane application."""
    return _APPLICATION


_DELIVERY_PROTOCOLS = frozenset({"a2a", "acp", "mcp", "cli"})


def trusted_delivery_identity(project_root: Path, *, principal: str, protocol: str) -> dict[str, Any]:
    """Build the delivery identity from facts the gateway established, never from caller assertions.

    ``principal`` is the authenticated shared principal (or ``local`` for the in-process owner); the project
    id is the declared identity of the served root; ``protocol`` is the adapter label, limited to a closed set.
    No delegated ``subject`` is accepted until a verified delegation mechanism exists.
    """
    from audiagentic.components.project.project_api import project_id as declared_project_id
    from audiagentic.foundation.contracts.errors import make_error

    if protocol not in _DELIVERY_PROTOCOLS:
        raise make_error(prefix="CON", component="AGW", number=163, kind="agent-work",
                         message="A delivery identity needs a principal, protocol, project, Context and message id",
                         details={"protocol": protocol})
    return {"principal": principal, "subject": None, "protocol": protocol,
            "project_id": declared_project_id(project_root)[0], "target_generation": None}


_WAIT_MAX_SECONDS = 600.0


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
