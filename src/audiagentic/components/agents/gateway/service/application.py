"""Framework-neutral application hosted by the standalone gateway service."""

from __future__ import annotations

import os
import secrets
from pathlib import Path
from typing import Any

from audiagentic.components.agents.contracts.execution_context import SubmissionEnvelope
from audiagentic.components.agents.gateway.application import GatewayApplication
from audiagentic.components.agents.gateway.operations import (
    GatewayOperationsApplication,
    ManagementCommand,
    ManagementOperationKind,
    ManagementOperationStore,
)
from audiagentic.components.agents.gateway.service.contract import (
    MAX_LEASE_TTL_SECONDS,
    PROTOCOL_VERSION,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError, make_error_factory
from audiagentic.foundation.system.managed_service import ManagedServiceStore

service_validation_error = make_error_factory("VAL", "AGSV", "gateway-service")
service_conflict_error = make_error_factory("CON", "AGSV", "gateway-service")

CAPABILITIES = (
    "requests.submit",
    "requests.status",
    "requests.diagnostics",
    "requests.recover",
    "requests.response",
    "conversations.focus-existing",
    "requests.wait",
    "requests.cancel",
    "sessions.list",
    "sessions.close",
    "sessions.control.v1",
    "sessions.resume-by-ref",
    "client-leases.v1",
    "service-lifecycle.v1",
    "gateway-operations.v1",  # SH24: typed operator-operation authority
    "contexts.open",
    "contexts.get",
    "contexts.list",
    "contexts.close",
    "work.submit",
    "work.get",
    "work.list",
    "work.message",
    "work.cancel",
    "work.output",
)


class GatewayServiceApplication:
    """Closed v1 operation router plus managed client-lease control."""

    def __init__(
        self,
        application: GatewayApplication,
        service_store: ManagedServiceStore,
        *,
        lifecycle: Any = None,
        dashboard_recent_seconds: int | None = None,
    ) -> None:
        self._application = application
        self._service_store = service_store
        # SH10: host-injected GatewayLifecycleController exposing the operator
        # status/drain/resume/stop surface; absent for bare in-process hosting.
        self._lifecycle = lifecycle
        self._dashboard_recent_seconds = dashboard_recent_seconds
        self._dashboard_action_token = secrets.token_urlsafe(32)
        # A distinct durable authority for gateway operator operations.  It
        # deliberately does not own request/session state or the work queue.
        self._operations = GatewayOperationsApplication(
            ManagementOperationStore(service_store.root)
        )

    def health(self) -> dict[str, Any]:
        record = self._service_store.read()
        return {
            "service": "agent-execution-gateway",
            "protocol-version": PROTOCOL_VERSION,
            "owner-epoch": record.owner_epoch,
            "lifetime-scope": None if record.process is None else record.process.scope,
            "state": record.state,
            "endpoint": None
            if record.endpoint is None
            else {
                "protocol": record.endpoint.protocol,
                "address": record.endpoint.address,
            },
            "capabilities": list(CAPABILITIES),
        }

    def dashboard_snapshot(self, recent_seconds: int | None = None) -> dict[str, Any]:
        """Read-only machine-wide dashboard data for the loopback page."""
        from audiagentic.components.agents.gateway.service.dashboard import dashboard_snapshot

        return dashboard_snapshot(
            self._service_store.root,
            recent_seconds=recent_seconds,
            configured_recent_seconds=self._dashboard_recent_seconds,
        )

    @property
    def dashboard_action_token(self) -> str:
        """Per-process token used only by the rendered dashboard action."""
        return self._dashboard_action_token

    def focus_dashboard_request(self, request_id: str) -> dict[str, Any]:
        """Resolve a dashboard request id across known projects and focus it."""
        from audiagentic.components.agents.gateway.service.known_projects import load_known_projects

        matches = []
        registry = load_known_projects(self._service_store.root / "known-projects.json")
        for known in registry.projects:
            if not known.project_root.exists():
                continue
            try:
                from audiagentic.components.agents.gateway import store as gateway_store

                gateway_store.read_record(known.project_root, request_id)
            except Exception:
                continue
            matches.append(known.project_root)
        if len(matches) != 1:
            return {
                "request-id": request_id,
                "outcome": "not-found" if not matches else "ambiguous",
                "reason": "request-project-not-found" if not matches else "request-id-not-unique",
            }
        return self._application.focus_execution_chat(matches[0], request_id)

    def acquire_client(
        self,
        client_instance_id: str,
        *,
        ttl_seconds: float,
        protocol_version: str,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        _require_protocol(protocol_version)
        _require_ttl(ttl_seconds)
        record = self._service_store.read()
        updated, lease = self._service_store.acquire_lease(
            client_instance_id,
            ttl_seconds=ttl_seconds,
            expected_epoch=record.owner_epoch,
            correlation_id=correlation_id,
        )
        return {
            "lease-id": lease.lease_id,
            "owner-epoch": lease.owner_epoch,
            "expires-at": lease.expires_at,
            "service-revision": updated.revision,
        }

    def renew_client(
        self,
        lease_id: str,
        *,
        ttl_seconds: float,
        owner_epoch: str,
        protocol_version: str,
    ) -> dict[str, Any]:
        _require_protocol(protocol_version)
        _require_ttl(ttl_seconds)
        updated = self._service_store.renew_lease(
            lease_id, ttl_seconds=ttl_seconds, expected_epoch=owner_epoch
        )
        lease = self._service_store.get_lease(lease_id)
        return {
            "lease-id": lease_id,
            "expires-at": lease.expires_at,
            "service-revision": updated.revision,
        }

    def release_client(
        self, lease_id: str, *, owner_epoch: str, protocol_version: str
    ) -> dict[str, Any]:
        _require_protocol(protocol_version)
        updated = self._service_store.release_lease(lease_id, expected_epoch=owner_epoch)
        return {
            "lease-id": lease_id,
            "state": self._service_store.get_lease(lease_id).state,
            "service-revision": updated.revision,
        }

    def invoke(
        self,
        operation: str,
        project_root: str,
        params: dict[str, Any] | None = None,
        *,
        protocol_version: str,
        owner_epoch: str,
        lease_id: str,
    ) -> Any:
        """Invoke one closed v1 gateway operation without transport concerns."""
        _require_protocol(protocol_version)
        try:
            self._service_store.require_active_lease(lease_id, expected_epoch=owner_epoch)
        except AudiaGenticError as exc:
            raise service_conflict_error(18, "gateway client lease is stale or inactive") from exc
        root = _canonical_root(project_root)
        arguments = dict(params or {})
        if operation in _WORK_PRODUCING_OPERATIONS and self._service_is_draining():
            raise service_conflict_error(
                29,
                "gateway is draining and will not admit new agent execution work",
                operation=operation,
            )
        if operation in _WORK_PRODUCING_OPERATIONS:
            self._record_project_encounter(root)
        if operation == "submit_execution_request":
            submitted = _validated_submission_arguments(root, arguments)
            return self._application.submit_execution_request(
                root,
                **submitted,
                _dispatch_owner_epoch=owner_epoch,
                _dispatch_service_root=str(self._service_store.root),
            )
        if operation == "get_execution_request":
            _reject_unknown(arguments, {"request_id"})
            return self._application.get_execution_request(root, _required(arguments, "request_id"))
        if operation == "get_execution_diagnostics":
            _reject_unknown(arguments, {"request_id", "limit"})
            limit = arguments.get("limit", 25)
            if isinstance(limit, bool) or not isinstance(limit, int):
                raise service_validation_error(32, "diagnostic limit must be an integer")
            return self._application.get_execution_diagnostics(
                root, _required(arguments, "request_id"), limit=limit
            )
        if operation == "recover_execution_request":
            _reject_unknown(arguments, {"request_id", "action", "expected_revision"})
            expected = arguments.get("expected_revision")
            if expected is not None and (isinstance(expected, bool) or not isinstance(expected, int)):
                raise service_validation_error(33, "expected_revision must be an integer")
            return self._application.recover_execution_request(
                root,
                _required(arguments, "request_id"),
                action=_required(arguments, "action"),
                expected_revision=expected,
            )
        if operation == "get_execution_response":
            _reject_unknown(arguments, {"request_id"})
            return self._application.get_execution_response(root, _required(arguments, "request_id"))
        if operation == "focus_execution_chat":
            _reject_unknown(arguments, {"request_id"})
            return self._application.focus_execution_chat(root, _required(arguments, "request_id"))
        if operation == "wait_execution_request":
            _reject_unknown(arguments, {"request_id", "timeout_seconds"})
            return self._application.wait_execution_request(
                root, _required(arguments, "request_id"), arguments.get("timeout_seconds")
            )
        if operation == "cancel_execution_request":
            return self._application.cancel_execution_request(
                root, _required(arguments, "request_id")
            )
        if operation == "request_runtime_status":
            return self._application.request_runtime_status(
                root, _required(arguments, "request_id")
            )
        if operation == "run_execution_request":
            submitted = _validated_submission_arguments(root, arguments)
            return self._application.run_execution_request(
                root,
                **submitted,
                _dispatch_owner_epoch=owner_epoch,
                _dispatch_service_root=str(self._service_store.root),
            )
        if operation == "list_execution_requests":
            _reject_unknown(arguments, {"state", "limit"})
            return self._application.list_execution_requests(
                root,
                state=_optional_string(arguments, "state"),
                limit=_optional_positive_int(arguments, "limit"),
            )
        if operation == "gateway_overview":
            return self._application.gateway_overview(root)
        if operation == "list_execution_sessions":
            _reject_unknown(arguments, {"state"})
            return self._application.list_execution_sessions(
                root, state=_optional_string(arguments, "state")
            )
        if operation == "close_execution_session":
            return self._application.close_execution_session(
                root, _required(arguments, "session_id")
            )
        if operation == "control_execution_session":
            _reject_unknown(arguments, {"session_id", "turn_id", "action", "control_id", "payload"})
            payload = arguments.get("payload")
            if payload is not None and not isinstance(payload, dict):
                raise service_validation_error(31, "session control payload must be an object")
            return self._application.control_execution_session(
                root,
                _required(arguments, "session_id"),
                turn_id=_optional_string(arguments, "turn_id"),
                action=_required(arguments, "action"),
                control_id=_required(arguments, "control_id"),
                payload=payload,
            )
        if operation == "resume_execution_session":
            _reject_unknown(
                arguments,
                {
                    "source_session_id",
                    "control_id",
                    "context_id",
                    "agent_definition_id",
                    "agent_definition_digest",
                    "role_ids",
                    "role_set_digest",
                    "execution_profile_digest",
                    "effective_capability_digest",
                    "model_id",
                },
            )
            return self._application.resume_execution_session(
                root,
                _required(arguments, "source_session_id"),
                control_id=_required(arguments, "control_id"),
                context_id=_optional_string(arguments, "context_id"),
                agent_definition_id=_optional_string(arguments, "agent_definition_id"),
                agent_definition_digest=_optional_string(arguments, "agent_definition_digest"),
                role_ids=_optional_string_list(arguments, "role_ids"),
                role_set_digest=_optional_string(arguments, "role_set_digest"),
                execution_profile_digest=_optional_string(arguments, "execution_profile_digest"),
                effective_capability_digest=_optional_string(
                    arguments, "effective_capability_digest"
                ),
                model_id=_optional_string(arguments, "model_id"),
            )
        if operation == "open_agent_context":
            _reject_unknown(arguments, {"agent_id", "title"})
            return self._application.open_agent_context(root, _required(arguments, "agent_id"), _optional_string(arguments, "title"))
        if operation == "get_agent_context":
            return self._application.get_agent_context(root, _required(arguments, "context_id"))
        if operation == "list_agent_contexts":
            return self._application.list_agent_contexts(root)
        if operation == "close_agent_context":
            return self._application.close_agent_context(root, _required(arguments, "context_id"))
        if operation == "submit_agent_work":
            message = arguments.get("message")
            if not isinstance(message, dict):
                raise service_validation_error(32, "work message must be an object")
            return self._application.submit_agent_work(root, _required(arguments, "context_id"), message, work_id=arguments.get("work_id"))
        if operation == "submit_agent_work_child":
            message = arguments.get("message")
            if not isinstance(message, dict):
                raise service_validation_error(34, "child work message must be an object")
            return self._application.submit_agent_work_child(root, _required(arguments, "parent_work_id"), message, work_id=arguments.get("work_id"), target_agent_id=arguments.get("target_agent_id"), timeout_seconds=arguments.get("timeout_seconds"))
        if operation == "get_agent_work":
            return self._application.get_agent_work(root, _required(arguments, "work_id"))
        if operation == "list_agent_work":
            return self._application.list_agent_work(root)
        if operation == "add_agent_work_message":
            message = arguments.get("message")
            if not isinstance(message, dict):
                raise service_validation_error(33, "work message must be an object")
            return self._application.add_agent_work_message(root, _required(arguments, "work_id"), message)
        if operation == "cancel_agent_work":
            return self._application.cancel_agent_work(root, _required(arguments, "work_id"))
        if operation == "read_agent_work_output":
            return self._application.read_agent_work_output(root, _required(arguments, "work_id"))
        if operation == "create_gateway_operation":
            return self._create_gateway_operation(arguments)
        if operation == "get_gateway_operation":
            _reject_unknown(arguments, {"operation_id"})
            return self._operations.get_operation(_required(arguments, "operation_id"))
        if operation == "list_gateway_operations":
            _reject_unknown(arguments, {"limit"})
            limit = arguments.get("limit", 100)
            if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0 or limit > 1000:
                raise service_validation_error(29, "gateway operation limit must be an integer from 1 to 1000")
            return {"operations": self._operations.list_operations(limit=limit)}
        if operation == "service_status":
            return self._lifecycle_controller().status()
        if operation == "service_drain":
            return self._lifecycle_controller().request_drain()
        if operation == "service_resume":
            if self._operations_active():
                raise service_conflict_error(
                    30, "gateway has active operator operations and cannot resume admission"
                )
            return self._lifecycle_controller().request_resume()
        if operation == "service_stop":
            _reject_unknown(arguments, {"force"})
            force = arguments.get("force", False)
            if not isinstance(force, bool):
                raise service_validation_error(26, "service_stop force must be a boolean")
            return self._lifecycle_controller().request_stop(force=force)
        raise service_validation_error(1, "unknown gateway service operation", operation=operation)

    def _lifecycle_controller(self) -> Any:
        if self._lifecycle is None:
            raise service_validation_error(
                25, "service lifecycle operations require the standalone service host"
            )
        return self._lifecycle

    def _record_project_encounter(self, project_root: Path) -> None:
        """Record a gpt-auto project's last-seen time in the known-projects
        registry (GP26). Best-effort and advisory: the registry is a startup
        scan cache, never an availability dependency, so a write failure here
        is intentionally swallowed."""
        try:
            from audiagentic.components.agents.gateway.service.known_projects import (
                record_known_project,
            )

            record_known_project(
                self._service_store.root / "known-projects.json",
                project_root=project_root,
            )
        except Exception:  # noqa: BLE001
            # Registry writes must never affect request admission.
            pass

    def _service_is_draining(self) -> bool:
        return self._service_store.read().state == "draining"

    def _operations_active(self) -> bool:
        return self._operations.has_active_operations()

    def _create_gateway_operation(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Translate the closed service payload to the gateway-operations API."""
        _reject_unknown(arguments, {"operation_id", "kind", "scope", "correlation_id"})
        raw_kind = _required(arguments, "kind")
        try:
            kind = ManagementOperationKind(raw_kind)
        except ValueError as exc:
            raise service_validation_error(27, "gateway operation kind is invalid") from exc
        scope = arguments.get("scope")
        if not isinstance(scope, dict):
            raise service_validation_error(28, "gateway operation scope must be a mapping")
        correlation_id = _optional_string(arguments, "correlation_id")
        return self._operations.create_operation(
            ManagementCommand(
                operation_id=_required(arguments, "operation_id"),
                kind=kind,
                scope=scope,
                correlation_id=correlation_id,
            )
        )


def _required(arguments: dict[str, Any], name: str) -> Any:
    value = arguments.get(name)
    if not isinstance(value, str) or not value:
        raise service_validation_error(
            2, "gateway service operation parameter is required", field=name
        )
    return value


_SUBMISSION_ARGUMENTS = {
    "agent_id",
    "execution_profile_id",
    "prompt_body",
    "mode",
    "source",
    "metadata",
    "session_id",
    "session_keep_alive",
    "workspace_name",
    "execution_context_fingerprint",
    "component_profile",
}

# Older MCP façades may continue to serialize the removed caller-controlled
# timeout/session-bound fields as explicit ``null`` values until that process
# is reloaded.  Null carries no authority and is safe to discard at this
# boundary; a non-null value remains an invalid request rather than silently
# reintroducing caller-controlled watchdog policy.
_RETIRED_SUBMISSION_ARGUMENTS = frozenset(
    {"timeout_seconds", "session_idle_timeout_seconds", "session_max_lifetime_seconds"}
)


def _validated_submission_arguments(
    project_root: Path, arguments: dict[str, Any]
) -> dict[str, Any]:
    """Validate the wire submission through SH02's canonical envelope."""
    for name in _RETIRED_SUBMISSION_ARGUMENTS:
        if name in arguments:
            value = arguments.pop(name)
            if value is not None:
                raise service_validation_error(
                    22,
                    "gateway service operation contains retired parameters",
                    fields=[name],
                )
    _reject_unknown(arguments, _SUBMISSION_ARGUMENTS)
    metadata = arguments.get("metadata")
    if metadata is not None and not isinstance(metadata, dict):
        raise service_validation_error(21, "gateway submission metadata must be a mapping")
    if "workspace_name" in arguments:
        arguments["workspace_name"] = _optional_string(arguments, "workspace_name")
    metadata = dict(metadata or {})
    envelope = SubmissionEnvelope.from_mapping(
        {
            "project_root": str(project_root),
            "schema_version": metadata.get("schema_version", 1),
            "idempotency_key": metadata.get("idempotency_key"),
            "correlation_id": metadata.get("correlation_id"),
            "source": arguments.get("source"),
            "execution_profile_id": arguments.get("execution_profile_id"),
            "provider_id": metadata.get("provider_id"),
            "model_id": metadata.get("model_id"),
            "component_profile": arguments.get("component_profile"),
            "mode": arguments.get("mode", "async"),
            # Submission execution is activity/watchdog governed. The RPC
            # boundary deliberately has no caller-controlled wall-clock
            # deadline; passive wait operations remain independent.
            "timeout_seconds": None,
            "session": {
                "session_id": arguments.get("session_id"),
                "keep_alive": arguments.get("session_keep_alive"),
                "idle_timeout_seconds": None,
                "max_lifetime_seconds": None,
            },
            "prompt_body": arguments.get("prompt_body"),
            "metadata": metadata,
        }
    )
    envelope.validate()
    return arguments


def _reject_unknown(arguments: dict[str, Any], allowed: set[str]) -> None:
    unknown = sorted(set(arguments) - allowed)
    if unknown:
        raise service_validation_error(
            22, "gateway service operation contains unknown parameters", fields=unknown
        )


def _optional_string(arguments: dict[str, Any], name: str) -> str | None:
    value = arguments.get(name)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise service_validation_error(23, "gateway service parameter must be a string", field=name)
    return value


def _optional_string_list(arguments: dict[str, Any], name: str) -> list[str] | None:
    value = arguments.get(name)
    if value is None:
        return None
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise service_validation_error(
            25, "gateway service parameter must be a list of non-empty strings", field=name
        )
    return value


def _optional_positive_int(arguments: dict[str, Any], name: str) -> int | None:
    value = arguments.get(name)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise service_validation_error(
            24, "gateway service parameter must be a positive integer", field=name
        )
    return value


def _require_protocol(value: str) -> None:
    if value != PROTOCOL_VERSION:
        raise service_validation_error(
            13,
            "gateway service protocol version is incompatible",
            expected=PROTOCOL_VERSION,
            actual=value,
        )


def _require_ttl(value: float) -> None:
    if value > MAX_LEASE_TTL_SECONDS:
        raise service_validation_error(
            19,
            "gateway client lease ttl exceeds the service maximum",
            maximum=MAX_LEASE_TTL_SECONDS,
        )


def _canonical_root(value: str) -> Path:
    root = Path(value)
    if not root.is_absolute():
        raise service_validation_error(20, "gateway project root must be absolute")
    canonical = root.resolve(strict=False)
    if os.path.normcase(str(root)) != os.path.normcase(str(canonical)):
        raise service_validation_error(20, "gateway project root must be canonical")
    return canonical


_WORK_PRODUCING_OPERATIONS = frozenset(
    {"submit_execution_request", "run_execution_request", "resume_execution_session", "submit_agent_work"}
)


__all__ = ["CAPABILITIES", "GatewayServiceApplication", "PROTOCOL_VERSION"]
