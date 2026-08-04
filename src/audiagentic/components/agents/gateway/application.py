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
    def resume_execution_session(
        self, project_root: Path, source_session_id: str, **kwargs: Any
    ) -> dict[str, Any]: ...


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

    def resume_execution_session(
        self, project_root: Path, source_session_id: str, **kwargs: Any
    ) -> dict[str, Any]:
        return self._api().resume_execution_session(project_root, source_session_id, **kwargs)


_APPLICATION: GatewayApplication = InProcessGatewayApplication()


def get_gateway_application() -> GatewayApplication:
    """Return this process's sole gateway control-plane application."""
    return _APPLICATION
