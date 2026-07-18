"""Framework-neutral application hosted by the standalone gateway service."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from audiagentic.components.agents.agents_gateway_application import GatewayApplication
from audiagentic.components.agents.agents_gateway_service_contract import (
    MAX_LEASE_TTL_SECONDS,
    PROTOCOL_VERSION,
)
from audiagentic.components.agents.contracts.execution_context import SubmissionEnvelope
from audiagentic.foundation.contracts.errors import AudiaGenticError, make_error_factory
from audiagentic.foundation.system.managed_service import ManagedServiceStore

service_validation_error = make_error_factory("VAL", "AGSV", "gateway-service")
service_conflict_error = make_error_factory("CON", "AGSV", "gateway-service")

CAPABILITIES = (
    "requests.submit",
    "requests.status",
    "requests.wait",
    "requests.cancel",
    "sessions.list",
    "sessions.close",
    "client-leases.v1",
    "service-lifecycle.v1",
)


class GatewayServiceApplication:
    """Closed v1 operation router plus managed client-lease control."""

    def __init__(
        self,
        application: GatewayApplication,
        service_store: ManagedServiceStore,
        *,
        lifecycle: Any = None,
    ) -> None:
        self._application = application
        self._service_store = service_store
        # SH10: host-injected GatewayLifecycleController exposing the operator
        # status/drain/resume/stop surface; absent for bare in-process hosting.
        self._lifecycle = lifecycle

    def health(self) -> dict[str, Any]:
        record = self._service_store.read()
        return {
            "service": "agent-llm-gateway",
            "protocol-version": PROTOCOL_VERSION,
            "owner-epoch": record.owner_epoch,
            "lifetime-scope": None if record.process is None else record.process.scope,
            "state": record.state,
            "endpoint": None if record.endpoint is None else {
                "protocol": record.endpoint.protocol,
                "address": record.endpoint.address,
            },
            "capabilities": list(CAPABILITIES),
        }

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
        return {"lease-id": lease_id, "expires-at": lease.expires_at, "service-revision": updated.revision}

    def release_client(
        self, lease_id: str, *, owner_epoch: str, protocol_version: str
    ) -> dict[str, Any]:
        _require_protocol(protocol_version)
        updated = self._service_store.release_lease(lease_id, expected_epoch=owner_epoch)
        return {"lease-id": lease_id, "state": self._service_store.get_lease(lease_id).state,
                "service-revision": updated.revision}

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
            self._service_store.require_active_lease(
                lease_id, expected_epoch=owner_epoch
            )
        except AudiaGenticError as exc:
            raise service_conflict_error(
                18, "gateway client lease is stale or inactive"
            ) from exc
        root = _canonical_root(project_root)
        arguments = dict(params or {})
        if operation == "submit_llm_request":
            submitted = _validated_submission_arguments(root, arguments)
            return self._application.submit_llm_request(
                root, **submitted, _dispatch_owner_epoch=owner_epoch
            )
        if operation == "get_llm_request":
            return self._application.get_llm_request(root, _required(arguments, "request_id"))
        if operation == "wait_llm_request":
            return self._application.wait_llm_request(
                root, _required(arguments, "request_id"), arguments.get("timeout_seconds")
            )
        if operation == "cancel_llm_request":
            return self._application.cancel_llm_request(root, _required(arguments, "request_id"))
        if operation == "run_llm_request":
            submitted = _validated_submission_arguments(root, arguments)
            return self._application.run_llm_request(
                root, **submitted, _dispatch_owner_epoch=owner_epoch
            )
        if operation == "list_llm_requests":
            _reject_unknown(arguments, {"state", "limit"})
            return self._application.list_llm_requests(
                root,
                state=_optional_string(arguments, "state"),
                limit=_optional_positive_int(arguments, "limit"),
            )
        if operation == "gateway_overview":
            return self._application.gateway_overview(root)
        if operation == "list_llm_sessions":
            _reject_unknown(arguments, {"state"})
            return self._application.list_llm_sessions(
                root, state=_optional_string(arguments, "state")
            )
        if operation == "close_llm_session":
            return self._application.close_llm_session(root, _required(arguments, "session_id"))
        if operation == "service_status":
            return self._lifecycle_controller().status()
        if operation == "service_drain":
            return self._lifecycle_controller().request_drain()
        if operation == "service_resume":
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


def _required(arguments: dict[str, Any], name: str) -> Any:
    value = arguments.get(name)
    if not isinstance(value, str) or not value:
        raise service_validation_error(2, "gateway service operation parameter is required", field=name)
    return value


_SUBMISSION_ARGUMENTS = {
    "agent_profile_id",
    "prompt_body",
    "mode",
    "timeout_seconds",
    "source",
    "metadata",
    "session_id",
    "session_keep_alive",
    "session_idle_timeout_seconds",
    "session_max_lifetime_seconds",
    "component_profile",
}


def _validated_submission_arguments(
    project_root: Path, arguments: dict[str, Any]
) -> dict[str, Any]:
    """Validate the wire submission through SH02's canonical envelope."""
    _reject_unknown(arguments, _SUBMISSION_ARGUMENTS)
    metadata = arguments.get("metadata")
    if metadata is not None and not isinstance(metadata, dict):
        raise service_validation_error(21, "gateway submission metadata must be a mapping")
    metadata = dict(metadata or {})
    envelope = SubmissionEnvelope.from_mapping(
        {
            "project_root": str(project_root),
            "schema_version": metadata.get("schema_version", 1),
            "idempotency_key": metadata.get("idempotency_key"),
            "correlation_id": metadata.get("correlation_id"),
            "source": arguments.get("source"),
            "agent_profile_id": arguments.get("agent_profile_id"),
            "provider_id": metadata.get("provider_id"),
            "model_id": metadata.get("model_id"),
            "component_profile": arguments.get("component_profile"),
            "mode": arguments.get("mode", "async"),
            "timeout_seconds": arguments.get("timeout_seconds"),
            "session": {
                "session_id": arguments.get("session_id"),
                "keep_alive": arguments.get("session_keep_alive", False),
                "idle_timeout_seconds": arguments.get("session_idle_timeout_seconds"),
                "max_lifetime_seconds": arguments.get("session_max_lifetime_seconds"),
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


__all__ = ["CAPABILITIES", "GatewayServiceApplication", "PROTOCOL_VERSION"]
