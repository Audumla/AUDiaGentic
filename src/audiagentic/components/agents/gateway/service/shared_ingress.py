"""Agents-owned shared ingress policy over the existing service application.

The TLS reverse proxy forwards only /shared/v1 to this loopback backend. No
forwarded identity header, client path or client execution environment is trusted.
"""
from __future__ import annotations

import hashlib
import hmac
from typing import Any

from audiagentic.components.agents.gateway.node.admission_contract import (
    NodeSubmissionContext,
    SourceWorkspaceIdentity,
)
from audiagentic.components.agents.gateway.remote_client import load_auth_token
from audiagentic.components.agents.gateway.service.shared_config import (
    SharedGatewayPrincipal,
    SharedGatewayServerConfig,
)
from audiagentic.foundation.contracts.errors import make_error_factory

_error = make_error_factory("VAL", "AGSV", "gateway-service")

# Explicitly exclude operator controls, focus, purge and future node/protocol APIs.
_ACTIONS = {
    **dict.fromkeys((
        "list_agent_definition_cards",
        "get_execution_request", "get_execution_diagnostics", "get_execution_response",
        "get_execution_response_payload", "get_execution_failure_response",
        "wait_execution_request", "list_execution_requests", "list_execution_sessions",
        "request_runtime_status", "get_execution_observations", "get_execution_evidence",
    ), "read"),
    "submit_execution_request": "submit",
    "cancel_execution_request": "cancel",
    "close_execution_session": "session",
    "resume_execution_session": "session",
    "recover_execution_request": "session",
    "complete_execution_from_provider": "session",
}
_SUBMISSION = frozenset({
    "agent_id", "execution_profile_id", "prompt_body", "mode", "source", "metadata",
    "session_id", "session_keep_alive", "new_session", "title", "logical_client_id",
    "node_id", "workspace_id", "source_workspace",
})
_METADATA = frozenset({"schema_version", "idempotency_key", "correlation_id"})


class SharedGatewayIngress:
    def __init__(self, config: SharedGatewayServerConfig) -> None:
        self.config = config
        self._credentials = tuple((p, load_auth_token(p.token_file)) for p in config.principals)
        if len({token for _, token in self._credentials}) != len(self._credentials):
            raise _error(11, "Shared gateway principals require distinct credentials")

    def authenticate(self, authorization: str) -> SharedGatewayPrincipal:
        matched = None
        for principal, token in self._credentials:
            if hmac.compare_digest(authorization.encode(), f"Bearer {token}".encode()):
                matched = principal
        if matched is None:
            raise _error(5, "Shared gateway authentication failed")
        return matched

    def prepare_call(self, principal: SharedGatewayPrincipal, body: dict[str, Any], *, client_instance_id: str) -> tuple[str, str, dict[str, Any]]:
        expected = {"operation", "project-id", "params", "protocol-version", "owner-epoch", "lease-id"}
        if set(body) != expected:
            raise _error(22, "Shared gateway call contains invalid fields")
        operation, project = body.get("operation"), body.get("project-id")
        if not isinstance(operation, str) or not isinstance(project, str):
            raise _error(23, "Shared gateway operation and project must be strings")
        action = _ACTIONS.get(operation)
        if action is None or action not in principal.actions or project not in principal.projects:
            raise _error(5, "Shared gateway action or project is not authorized")
        if project not in self.config.projects:
            raise _error(5, "Shared gateway project is not configured")
        params = body.get("params")
        if not isinstance(params, dict):
            raise _error(22, "Shared gateway params must be an object")
        params = dict(params)
        if operation == "submit_execution_request":
            if params.keys() - _SUBMISSION:
                raise _error(22, "Shared submission contains unsupported parameters")
            node_fields = {"node_id", "workspace_id", "source_workspace"}
            if node_fields.intersection(params) and not node_fields <= params.keys():
                raise _error(22, "Node submission requires complete recipient and caller context")
            metadata = params.get("metadata") or {}
            if not isinstance(metadata, dict) or metadata.keys() - _METADATA:
                raise _error(22, "Shared submission metadata contains unsupported parameters")
            metadata = dict(metadata)
            key = metadata.get("idempotency_key")
            if key is not None:
                if not isinstance(key, str) or not key or len(key) > 200:
                    raise _error(23, "Shared idempotency key is invalid")
                metadata["idempotency_key"] = "shared:" + hashlib.sha256(
                    f"{principal.principal_id}:{key}".encode()
                ).hexdigest()
            params["metadata"] = metadata
            # The durable lease and authenticated principal, never a caller alias,
            # establish the default conversation boundary.
            alias = params.get("logical_client_id") or client_instance_id
            if not isinstance(alias, str) or len(alias) > 200:
                raise _error(23, "Shared logical client identity is invalid")
            params["logical_client_id"] = "shared:" + hashlib.sha256(
                f"{principal.principal_id}:{alias}".encode()
            ).hexdigest()
        if operation == "resume_execution_session" and params.keys() - {"source_session_id", "control_id"}:
            raise _error(22, "Shared resume cannot override execution authority")
        return operation, str(self.config.projects[project]), params

    def node_submission_context(
        self, principal: SharedGatewayPrincipal, project_id: str,
        params: dict[str, Any], *, source_node_token: str,
    ) -> tuple[NodeSubmissionContext, dict[str, Any]]:
        """Separate authenticated ingress scope from untrusted operation params.

        Source credential verification remains in NodeGrantAuthority under its
        current grant/revocation lock. Never resolve the foreign locator here.
        """
        if project_id not in principal.projects or project_id not in self.config.projects or "submit" not in principal.actions:
            raise _error(5, "Node submission principal or project is not authorized")
        source = params.get("source_workspace")
        if not isinstance(source, dict) or set(source) != {"identity", "caller-root"}:
            raise _error(22, "Node submission requires connector-owned caller context")
        context = NodeSubmissionContext(
            principal.principal_id, self.config.server_id, project_id,
            params.get("node_id"), params.get("workspace_id"),
            SourceWorkspaceIdentity.from_mapping(source["identity"]),
            source["caller-root"], source_node_token,
        )
        arguments = {key: value for key, value in params.items()
                     if key not in {"node_id", "workspace_id", "source_workspace"}}
        return context, arguments

    def health(self, application: Any, principal: SharedGatewayPrincipal) -> dict[str, Any]:
        raw = application.health()
        return {key: raw[key] for key in ("service", "protocol-version", "owner-epoch", "state")} | {
            "server-id": self.config.server_id,
            "projects": sorted(principal.projects),
            "capabilities": sorted(operation for operation, action in _ACTIONS.items() if action in principal.actions),
        }
