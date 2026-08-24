"""Framework-neutral GatewayClient implementation over authenticated loopback HTTP."""

from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path
from typing import Any, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from audiagentic.components.agents.gateway.service.contract import (
    CALL_ROUTE,
    HEALTH_ROUTE,
    LEASE_ACQUIRE_ROUTE,
    LEASE_RELEASE_ROUTE,
    LEASE_RENEW_ROUTE,
    MAX_LEASE_TTL_SECONDS,
    PROTOCOL_VERSION,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError, make_error_factory

client_validation_error = make_error_factory("VAL", "AGSV", "gateway-service")
client_network_error = make_error_factory("NET", "AGSV", "gateway-service")
_DEFAULT_TRANSPORT_TIMEOUT = object()


class StandaloneGatewayClient:
    """Explicit opt-in client; it never auto-discovers or falls back in-process."""

    def __init__(
        self,
        endpoint: str,
        auth_token: str,
        *,
        request_timeout: float = 30.0,
        lease_ttl_seconds: float = 120.0,
    ) -> None:
        self._endpoint = _validate_endpoint(endpoint)
        if not auth_token or any(character.isspace() for character in auth_token):
            raise client_validation_error(11, "gateway service auth token is invalid")
        if request_timeout <= 0 or lease_ttl_seconds <= 0:
            raise client_validation_error(12, "gateway client timeout values must be positive")
        if lease_ttl_seconds > MAX_LEASE_TTL_SECONDS:
            raise client_validation_error(
                19,
                "gateway client lease ttl exceeds the service maximum",
                maximum=MAX_LEASE_TTL_SECONDS,
            )
        self._auth_token = auth_token
        self._request_timeout = request_timeout
        self._lease_ttl_seconds = lease_ttl_seconds
        self._client_instance_id = f"client_{uuid.uuid4().hex[:16]}"
        self._lease_id: str | None = None
        self._owner_epoch: str | None = None
        self._renew_at = 0.0
        self._service_lifetime_scope: str | None = None
        self._state_lock = threading.Lock()

    def connect(self) -> dict[str, Any]:
        with self._state_lock:
            if self._lease_id is not None:
                return self.health()
            health = self.health()
            if health.get("protocol-version") != PROTOCOL_VERSION:
                raise client_validation_error(
                    13,
                    "gateway service protocol version is incompatible",
                    expected=PROTOCOL_VERSION,
                    actual=health.get("protocol-version"),
                )
            lease = _response_mapping(
                self._request(
                    LEASE_ACQUIRE_ROUTE,
                    {
                        "client-instance-id": self._client_instance_id,
                        "ttl-seconds": self._lease_ttl_seconds,
                        "protocol-version": PROTOCOL_VERSION,
                    },
                )
            )
            if lease.get("owner-epoch") != health.get("owner-epoch"):
                raise client_validation_error(14, "gateway owner changed during client attach")
            self._lease_id = _response_string(lease, "lease-id")
            self._owner_epoch = _response_string(lease, "owner-epoch")
            self._renew_at = time.monotonic() + self._lease_ttl_seconds / 2
            return health

    @property
    def service_lifetime_scope(self) -> str | None:
        """Return foundation process lifetime evidence for automatic startup."""
        return self._service_lifetime_scope

    def adopt_managed_lease(self, lease_id: str, owner_epoch: str, *, lifetime_scope: str) -> None:
        """Adopt the initial lease issued atomically by managed-service startup."""
        if not lease_id or not owner_epoch:
            raise client_validation_error(22, "managed gateway lease identity is invalid")
        if not lifetime_scope:
            raise client_validation_error(23, "managed gateway lifetime scope is invalid")
        with self._state_lock:
            if self._lease_id is not None:
                raise client_validation_error(24, "gateway client already has a lease")
            self._lease_id = lease_id
            self._owner_epoch = owner_epoch
            self._renew_at = time.monotonic() + self._lease_ttl_seconds / 2
            self._service_lifetime_scope = lifetime_scope

    def close(self) -> None:
        with self._state_lock:
            lease_id, epoch = self._lease_id, self._owner_epoch
            self._lease_id = None
            self._owner_epoch = None
            self._renew_at = 0.0
        if lease_id is None or epoch is None:
            return
        try:
            self._request(
                LEASE_RELEASE_ROUTE,
                {
                    "lease-id": lease_id,
                    "owner-epoch": epoch,
                    "protocol-version": PROTOCOL_VERSION,
                },
                # A service may already be leaving after an authorised stop;
                # release is best effort and must never hold process teardown
                # behind the normal request timeout.
                timeout=1.0,
            )
        except AudiaGenticError:
            pass

    def __enter__(self) -> StandaloneGatewayClient:
        self.connect()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def health(self) -> dict[str, Any]:
        return _response_mapping(
            self._request(HEALTH_ROUTE, None, method="GET", retry_network=True)
        )

    def submit_execution_request(self, project_root: Path, **kwargs: Any) -> dict[str, Any]:
        if "component_profile" not in kwargs:
            from audiagentic.foundation.paths.names import get_active_profile

            kwargs["component_profile"] = get_active_profile()
        return cast(dict[str, Any], self._call("submit_execution_request", project_root, kwargs))

    def get_execution_request(self, project_root: Path, request_id: str) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            self._call("get_execution_request", project_root, {"request_id": request_id}),
        )

    def get_execution_diagnostics(self, project_root: Path, request_id: str, *, limit: int = 25) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            self._call("get_execution_diagnostics", project_root, {"request_id": request_id, "limit": limit}),
        )

    def recover_execution_request(self, project_root: Path, request_id: str, **kwargs: Any) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            self._call("recover_execution_request", project_root, {"request_id": request_id, **kwargs}),
        )

    def get_execution_response(self, project_root: Path, request_id: str) -> str:
        return cast(
            str,
            self._call("get_execution_response", project_root, {"request_id": request_id}),
        )

    def wait_execution_request(
        self, project_root: Path, request_id: str, timeout_seconds: float | None = None
    ) -> dict[str, Any]:
        timeout = None if timeout_seconds is None else timeout_seconds + 5
        return cast(
            dict[str, Any],
            self._call(
                "wait_execution_request",
                project_root,
                {"request_id": request_id, "timeout_seconds": timeout_seconds},
                transport_timeout=timeout,
            ),
        )

    def cancel_execution_request(self, project_root: Path, request_id: str) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            self._call("cancel_execution_request", project_root, {"request_id": request_id}),
        )

    def request_runtime_status(self, project_root: Path, request_id: str) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            self._call("request_runtime_status", project_root, {"request_id": request_id}),
        )

    def run_execution_request(self, project_root: Path, **kwargs: Any) -> dict[str, Any]:
        if "component_profile" not in kwargs:
            from audiagentic.foundation.paths.names import get_active_profile

            kwargs["component_profile"] = get_active_profile()
        requested = kwargs.get("timeout_seconds")
        timeout = _DEFAULT_TRANSPORT_TIMEOUT if requested is None else float(requested) + 5  # noqa: RUF039
        return cast(
            dict[str, Any],
            self._call("run_execution_request", project_root, kwargs, transport_timeout=timeout),
        )

    def list_execution_requests(self, project_root: Path, **kwargs: Any) -> list[dict[str, Any]]:
        return cast(
            list[dict[str, Any]], self._call("list_execution_requests", project_root, kwargs)
        )

    def gateway_overview(self, project_root: Path) -> dict[str, Any]:
        return cast(dict[str, Any], self._call("gateway_overview", project_root, {}))

    def list_execution_sessions(self, project_root: Path, **kwargs: Any) -> list[dict[str, Any]]:
        return cast(
            list[dict[str, Any]], self._call("list_execution_sessions", project_root, kwargs)
        )

    def close_execution_session(self, project_root: Path, session_id: str) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            self._call("close_execution_session", project_root, {"session_id": session_id}),
        )

    def control_execution_session(
        self, project_root: Path, session_id: str, **kwargs: Any
    ) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            self._call(
                "control_execution_session",
                project_root,
                {"session_id": session_id, **kwargs},
            ),
        )

    def resume_execution_session(
        self, project_root: Path, source_session_id: str, **kwargs: Any
    ) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            self._call(
                "resume_execution_session",
                project_root,
                {"source_session_id": source_session_id, **kwargs},
            ),
        )

    def open_agent_context(self, project_root: Path, agent_id: str, title: str | None = None) -> dict[str, Any]:
        return cast(dict[str, Any], self._call("open_agent_context", project_root, {"agent_id": agent_id, "title": title}))

    def get_agent_context(self, project_root: Path, context_id: str) -> dict[str, Any]:
        return cast(dict[str, Any], self._call("get_agent_context", project_root, {"context_id": context_id}))

    def list_agent_contexts(self, project_root: Path) -> list[dict[str, Any]]:
        return cast(list[dict[str, Any]], self._call("list_agent_contexts", project_root, {}))

    def close_agent_context(self, project_root: Path, context_id: str) -> dict[str, Any]:
        return cast(dict[str, Any], self._call("close_agent_context", project_root, {"context_id": context_id}))

    def submit_agent_work(self, project_root: Path, context_id: str, message: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        return cast(dict[str, Any], self._call("submit_agent_work", project_root, {"context_id": context_id, "message": message, **kwargs}))

    def submit_agent_work_child(self, project_root: Path, parent_work_id: str, message: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        return cast(dict[str, Any], self._call("submit_agent_work_child", project_root, {"parent_work_id": parent_work_id, "message": message, **kwargs}))

    def get_agent_work(self, project_root: Path, work_id: str) -> dict[str, Any]:
        return cast(dict[str, Any], self._call("get_agent_work", project_root, {"work_id": work_id}))

    def list_agent_work(self, project_root: Path) -> list[dict[str, Any]]:
        return cast(list[dict[str, Any]], self._call("list_agent_work", project_root, {}))

    def add_agent_work_message(self, project_root: Path, work_id: str, message: dict[str, Any]) -> dict[str, Any]:
        return cast(dict[str, Any], self._call("add_agent_work_message", project_root, {"work_id": work_id, "message": message}))

    def cancel_agent_work(self, project_root: Path, work_id: str) -> dict[str, Any]:
        return cast(dict[str, Any], self._call("cancel_agent_work", project_root, {"work_id": work_id}))

    def read_agent_work_output(self, project_root: Path, work_id: str) -> dict[str, Any]:
        return cast(dict[str, Any], self._call("read_agent_work_output", project_root, {"work_id": work_id}))

    # SH10 operator lifecycle surface (service-scoped; project root is the
    # caller's admission context only).

    def service_status(self, project_root: Path) -> dict[str, Any]:
        return cast(dict[str, Any], self._call("service_status", project_root, {}))

    def service_drain(self, project_root: Path) -> dict[str, Any]:
        return cast(dict[str, Any], self._call("service_drain", project_root, {}))

    def service_resume(self, project_root: Path) -> dict[str, Any]:
        return cast(dict[str, Any], self._call("service_resume", project_root, {}))

    def service_stop(self, project_root: Path, *, force: bool = False) -> dict[str, Any]:
        return cast(dict[str, Any], self._call("service_stop", project_root, {"force": force}))

    # Gateway operator operations have a deliberately separate client
    # surface; they are not part of the activity GatewayClient protocol.

    def create_gateway_operation(
        self,
        project_root: Path,
        *,
        operation_id: str,
        kind: str,
        scope: dict[str, Any],
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "operation_id": operation_id,
            "kind": kind,
            "scope": scope,
        }
        if correlation_id is not None:
            params["correlation_id"] = correlation_id
        return cast(dict[str, Any], self._call("create_gateway_operation", project_root, params))

    def list_gateway_operations(self, project_root: Path, *, limit: int = 100) -> list[dict[str, Any]]:
        result = self._call("list_gateway_operations", project_root, {"limit": limit})
        if not isinstance(result, dict) or not isinstance(result.get("operations"), list):
            raise AudiaGenticError("IO-AGW-121", "agents", "gateway operation listing is invalid", {})
        return cast(list[dict[str, Any]], result["operations"])

    def get_gateway_operation(self, project_root: Path, operation_id: str) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            self._call("get_gateway_operation", project_root, {"operation_id": operation_id}),
        )

    def _call(
        self,
        operation: str,
        project_root: Path,
        params: dict[str, Any],
        *,
        transport_timeout: float | None | object = _DEFAULT_TRANSPORT_TIMEOUT,
    ) -> Any:
        root = project_root.expanduser().resolve(strict=False)
        self._ensure_lease()
        for attempt in range(2):
            with self._state_lock:
                lease_id, owner_epoch = self._lease_id, self._owner_epoch
            if lease_id is None or owner_epoch is None:
                raise client_network_error(3, "gateway client lease state is invalid")
            try:
                return self._request(
                    CALL_ROUTE,
                    {
                        "protocol-version": PROTOCOL_VERSION,
                        "owner-epoch": owner_epoch,
                        "lease-id": lease_id,
                        "operation": operation,
                        "project-root": str(root),
                        "params": params,
                    },
                    timeout=transport_timeout,
                )
            except AudiaGenticError as exc:
                if attempt > 0 or exc.code != "CON-AGSV-018":
                    raise
                self._clear_lease(lease_id)
                self.connect()
        raise AssertionError("bounded gateway reattach loop exhausted")

    def _ensure_lease(self) -> None:
        with self._state_lock:
            lease_id, owner_epoch, renew_at = (
                self._lease_id,
                self._owner_epoch,
                self._renew_at,
            )
        if lease_id is None or owner_epoch is None:
            self.connect()
            return
        if time.monotonic() < renew_at:
            return
        try:
            renewed = _response_mapping(
                self._request(
                    LEASE_RENEW_ROUTE,
                    {
                        "lease-id": lease_id,
                        "owner-epoch": owner_epoch,
                        "ttl-seconds": self._lease_ttl_seconds,
                        "protocol-version": PROTOCOL_VERSION,
                    },
                )
            )
        except AudiaGenticError as exc:
            if exc.code not in {"CON-MSVC-014", "CON-MSVC-019", "VAL-MSVC-020"}:
                raise
            self._clear_lease(lease_id)
            self.connect()
            return
        _response_string(renewed, "expires-at")
        with self._state_lock:
            if self._lease_id == lease_id:
                self._renew_at = time.monotonic() + self._lease_ttl_seconds / 2

    def _clear_lease(self, expected_lease_id: str) -> None:
        with self._state_lock:
            if self._lease_id != expected_lease_id:
                return
            self._lease_id = None
            self._owner_epoch = None
            self._renew_at = 0.0

    def _request(
        self,
        path: str,
        body: dict[str, Any] | None,
        *,
        method: str = "POST",
        timeout: float | None | object = _DEFAULT_TRANSPORT_TIMEOUT,
        retry_network: bool = False,
    ) -> Any:
        encoded = None if body is None else json.dumps(body).encode("utf-8")
        request = Request(
            f"{self._endpoint}{path}",
            data=encoded,
            method=method,
            headers={
                "Authorization": f"Bearer {self._auth_token}",
                "Content-Type": "application/json",
            },
        )
        attempts = 2 if retry_network else 1
        payload: dict[str, Any] | None = None
        for attempt in range(attempts):
            try:
                request_timeout = (
                    self._request_timeout
                    if timeout is _DEFAULT_TRANSPORT_TIMEOUT
                    else cast(float | None, timeout)
                )
                with urlopen(request, timeout=request_timeout) as response:
                    raw_payload = response.read()
            except HTTPError as exc:
                try:
                    payload = json.loads(exc.read().decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as decode_error:
                    raise client_network_error(
                        1, "gateway service returned an invalid error response"
                    ) from decode_error
                raise _remote_error(payload) from exc
            except (URLError, TimeoutError, OSError) as exc:
                if attempt + 1 < attempts:
                    time.sleep(min(0.05, self._request_timeout / 10))
                    continue
                raise client_network_error(
                    2, "gateway service is unavailable", endpoint=self._endpoint
                ) from exc
            try:
                payload = json.loads(raw_payload.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise client_network_error(3, "gateway service returned invalid JSON") from exc
            break
        if not isinstance(payload, dict) or payload.get("ok") is not True:  # noqa: SIM401
            raise client_network_error(3, "gateway service returned an invalid response envelope")
        result = payload.get("result")
        return result


def load_auth_token(path: Path) -> str:
    try:
        token = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise client_validation_error(
            15, "gateway auth token file is unreadable", path=str(path)
        ) from exc
    if not token or len(token) > 1024 or any(character.isspace() for character in token):
        raise client_validation_error(11, "gateway service auth token is invalid")
    return token


def _validate_endpoint(endpoint: str) -> str:
    parsed = urlparse(endpoint)
    try:
        port = parsed.port
    except ValueError as exc:
        raise client_validation_error(
            16, "gateway endpoint must be an explicit IPv4 loopback HTTP origin"
        ) from exc
    if (
        parsed.scheme != "http"
        or parsed.hostname != "127.0.0.1"
        or port is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise client_validation_error(
            16, "gateway endpoint must be an explicit IPv4 loopback HTTP origin"
        )
    return f"http://127.0.0.1:{port}"


def _response_mapping(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise client_network_error(3, "gateway service result must be a mapping")
    return cast(dict[str, Any], payload)


def _response_string(payload: dict[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value:
        raise client_network_error(3, "gateway service response field is invalid", field=field)
    return value


def _remote_error(payload: Any) -> AudiaGenticError:
    if not isinstance(payload, dict):
        return client_network_error(3, "gateway service returned an invalid error envelope")
    code = payload.get("error-code")
    kind = payload.get("error-kind")
    message = payload.get("message")
    details = payload.get("details")
    if not all(isinstance(value, str) and value for value in (code, kind, message)):
        return client_network_error(3, "gateway service returned an invalid error envelope")
    return AudiaGenticError(
        code=cast(str, code),
        kind=cast(str, kind),
        message=cast(str, message),
        details=details if isinstance(details, dict) else {},
    )


__all__ = ["StandaloneGatewayClient", "load_auth_token"]
