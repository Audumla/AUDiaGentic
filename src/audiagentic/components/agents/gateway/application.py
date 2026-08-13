"""Gateway application/control-plane boundary for the in-process backend.

This module is deliberately framework-neutral.  SH04 service transports will
host this application; SH03 inbound adapters reach it only through the client.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class GatewayApplication(Protocol):
    """Operations owned by the gateway control plane."""

    def submit_execution_request(self, project_root: Path, **kwargs: Any) -> dict[str, Any]: ...
    def get_execution_request(self, project_root: Path, request_id: str) -> dict[str, Any]: ...
    def wait_execution_request(
        self, project_root: Path, request_id: str, timeout_seconds: float | None = None
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
    def get_agent_work(self, project_root: Path, work_id: str) -> dict[str, Any]: ...
    def list_agent_work(self, project_root: Path) -> list[dict[str, Any]]: ...
    def add_agent_work_message(self, project_root: Path, work_id: str, message: dict[str, Any]) -> dict[str, Any]: ...
    def cancel_agent_work(self, project_root: Path, work_id: str) -> dict[str, Any]: ...
    def read_agent_work_output(self, project_root: Path, work_id: str) -> dict[str, Any]: ...


class InProcessGatewayApplication:
    """The existing API implementation presented as one control-plane owner."""

    @staticmethod
    def _api() -> Any:
        from audiagentic.components.agents.gateway import api as agents_gateway_api

        return agents_gateway_api

    def submit_execution_request(self, project_root: Path, **kwargs: Any) -> dict[str, Any]:
        return self._api().submit_execution_request(project_root, **kwargs)

    def get_execution_request(self, project_root: Path, request_id: str) -> dict[str, Any]:
        return self._api().get_execution_request(project_root, request_id)

    def wait_execution_request(
        self, project_root: Path, request_id: str, timeout_seconds: float | None = None
    ) -> dict[str, Any]:
        return self._api().wait_execution_request(project_root, request_id, timeout_seconds)

    def cancel_execution_request(self, project_root: Path, request_id: str) -> dict[str, Any]:
        return self._api().cancel_execution_request(project_root, request_id)

    def request_runtime_status(self, project_root: Path, request_id: str) -> dict[str, Any]:
        return self._api().request_runtime_status(project_root, request_id)

    def run_execution_request(self, project_root: Path, **kwargs: Any) -> dict[str, Any]:
        return self._api().run_execution_request(project_root, **kwargs)

    def list_execution_requests(self, project_root: Path, **kwargs: Any) -> list[dict[str, Any]]:
        return self._api().list_execution_requests(project_root, **kwargs)

    def gateway_overview(self, project_root: Path) -> dict[str, Any]:
        return self._api().gateway_overview(project_root)

    def list_execution_sessions(self, project_root: Path, **kwargs: Any) -> list[dict[str, Any]]:
        return self._api().list_execution_sessions(project_root, **kwargs)

    def close_execution_session(self, project_root: Path, session_id: str) -> dict[str, Any]:
        return self._api().close_execution_session(project_root, session_id)

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
