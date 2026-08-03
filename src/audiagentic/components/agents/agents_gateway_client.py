"""Public in-process client for the agent execution gateway.

Inbound surfaces depend on this module, never on the gateway implementation
modules.  SH03 keeps the current in-process control plane, but makes the
client boundary explicit so a later local-service client can implement the
same operations without changing MCP or event adapters.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any, Protocol

from audiagentic.components.agents.agents_gateway_application import (
    GatewayApplication,
    get_gateway_application,
)


class GatewayClient(Protocol):
    """Requester-facing gateway operations, independent of inbound transport."""

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


class InProcessGatewayClient:
    """SH03 backend adapter for the existing in-process control plane."""

    def __init__(self, application: GatewayApplication | None = None) -> None:
        self._application = application or get_gateway_application()

    def submit_execution_request(self, project_root: Path, **kwargs: Any) -> dict[str, Any]:
        return self._application.submit_execution_request(project_root, **kwargs)

    def get_execution_request(self, project_root: Path, request_id: str) -> dict[str, Any]:
        return self._application.get_execution_request(project_root, request_id)

    def wait_execution_request(
        self, project_root: Path, request_id: str, timeout_seconds: float | None = None
    ) -> dict[str, Any]:
        return self._application.wait_execution_request(project_root, request_id, timeout_seconds)

    def cancel_execution_request(self, project_root: Path, request_id: str) -> dict[str, Any]:
        return self._application.cancel_execution_request(project_root, request_id)

    def request_runtime_status(self, project_root: Path, request_id: str) -> dict[str, Any]:
        return self._application.request_runtime_status(project_root, request_id)

    def run_execution_request(self, project_root: Path, **kwargs: Any) -> dict[str, Any]:
        return self._application.run_execution_request(project_root, **kwargs)

    def list_execution_requests(self, project_root: Path, **kwargs: Any) -> list[dict[str, Any]]:
        return self._application.list_execution_requests(project_root, **kwargs)

    def gateway_overview(self, project_root: Path) -> dict[str, Any]:
        return self._application.gateway_overview(project_root)

    def list_execution_sessions(self, project_root: Path, **kwargs: Any) -> list[dict[str, Any]]:
        return self._application.list_execution_sessions(project_root, **kwargs)

    def close_execution_session(self, project_root: Path, session_id: str) -> dict[str, Any]:
        return self._application.close_execution_session(project_root, session_id)

    def resume_execution_session(
        self, project_root: Path, source_session_id: str, **kwargs: Any
    ) -> dict[str, Any]:
        return self._application.resume_execution_session(project_root, source_session_id, **kwargs)


_CLIENT_LOCK = threading.Lock()
_CLIENT: GatewayClient | None = None
_CLIENT_CONFIG: tuple[str, str | None, str | None] | None = None


def get_gateway_client() -> GatewayClient:
    """Return the explicitly selected in-process or standalone client."""
    from audiagentic.foundation.contracts.errors import make_error_factory

    config_error = make_error_factory("CFG", "AGSV", "gateway-service")
    mode = os.environ.get("AUDIAGENTIC_GATEWAY_MODE", "in-process").strip().lower()
    endpoint = os.environ.get("AUDIAGENTIC_GATEWAY_ENDPOINT")
    token_file = os.environ.get("AUDIAGENTIC_GATEWAY_TOKEN_FILE")
    config = (mode, endpoint, token_file)
    global _CLIENT, _CLIENT_CONFIG
    with _CLIENT_LOCK:
        if _CLIENT is not None and _CLIENT_CONFIG == config:
            return _CLIENT
        if _CLIENT is not None:
            close = getattr(_CLIENT, "close", None)
            if callable(close):
                close()
        if mode == "in-process":
            client: GatewayClient = InProcessGatewayClient()
        elif mode == "standalone":
            if not endpoint or not token_file:
                raise config_error(
                    1,
                    "standalone gateway requires explicit endpoint and token file",
                )
            from audiagentic.components.agents.agents_gateway_remote_client import (
                StandaloneGatewayClient,
                load_auth_token,
            )

            client = StandaloneGatewayClient(endpoint, load_auth_token(Path(token_file)))
        elif mode == "automatic":
            from audiagentic.components.agents.agents_gateway_bootstrap import (
                start_or_attach_gateway,
            )

            client = start_or_attach_gateway()
        else:
            raise config_error(2, "unknown gateway mode", mode=mode)
        _CLIENT = client
        _CLIENT_CONFIG = config
        return client


def reset_gateway_client() -> None:
    """Release the selected client; intended for process shutdown and tests."""
    global _CLIENT, _CLIENT_CONFIG
    with _CLIENT_LOCK:
        if _CLIENT is not None:
            close = getattr(_CLIENT, "close", None)
            if callable(close):
                close()
        _CLIENT = None
        _CLIENT_CONFIG = None
