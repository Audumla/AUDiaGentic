"""Authenticated loopback HTTP adapter for the standalone gateway service."""

from __future__ import annotations

import hmac
import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

from audiagentic.components.agents.gateway.service.application import (
    GatewayServiceApplication,
)
from audiagentic.components.agents.gateway.service.contract import (
    CALL_ROUTE,
    HEALTH_ROUTE,
    LEASE_ACQUIRE_ROUTE,
    LEASE_RELEASE_ROUTE,
    LEASE_RENEW_ROUTE,
)
from audiagentic.foundation.contracts.errors import (
    AudiaGenticError,
    make_error_factory,
    to_error_envelope,
)

logger = logging.getLogger(__name__)
MAX_REQUEST_BYTES = 4 * 1024 * 1024
transport_error = make_error_factory("VAL", "AGSV", "gateway-service")
internal_error = make_error_factory("INT", "AGSV", "gateway-service")


class GatewayHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        application: GatewayServiceApplication,
        auth_token: str,
        *,
        dashboard_path: str = "/dashboard",
        dashboard_recent_seconds: int | None = None,
        shared_config: Any = None,
    ) -> None:
        if address[0] != "127.0.0.1":
            raise transport_error(3, "gateway service must bind to IPv4 loopback")
        self.application = application
        self.shared_ingress = None
        if shared_config is not None:
            from .shared_ingress import SharedGatewayIngress

            self.shared_ingress = SharedGatewayIngress(shared_config)
        self.auth_token = auth_token
        self.dashboard_path = _dashboard_path(dashboard_path)
        self.dashboard_snapshot_path = f"{self.dashboard_path}/snapshot"
        self.dashboard_focus_path = f"{self.dashboard_path}/focus"
        self.dashboard_purge_session_path = f"{self.dashboard_path}/purge-session"
        self.dashboard_restart_path = f"{self.dashboard_path}/restart"
        self.dashboard_cancel_path = f"{self.dashboard_path}/cancel-request"
        self.dashboard_complete_path = f"{self.dashboard_path}/complete-from-provider"
        self.dashboard_close_session_path = f"{self.dashboard_path}/close-session"
        self.dashboard_archive_path = f"{self.dashboard_path}/archive-request"
        self.dashboard_operation_path = f"{self.dashboard_path}/operation-status"
        self.dashboard_image_path = f"{self.dashboard_path}/project-image"
        self.dashboard_recent_seconds = dashboard_recent_seconds
        super().__init__(address, GatewayHTTPRequestHandler)


class GatewayHTTPRequestHandler(BaseHTTPRequestHandler):
    server: GatewayHTTPServer  # pyright: ignore[reportIncompatibleVariableOverride]

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
        self._dispatch("GET")

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
        self._dispatch("POST")

    def _dispatch(self, method: str) -> None:
        try:
            if self.server.shared_ingress is not None:
                self._dispatch_shared(method)
                return
            # The dashboard is a redacted, loopback-only operator surface.
            # It must remain usable by an ordinary browser, which cannot know
            # the service bearer token.  Every mutable/control route remains
            # authenticated below.
            parsed = urlsplit(self.path)
            if method == "GET" and parsed.path == f"{self.server.dashboard_path}/client-icon":
                from .client_icons import read_client_icon

                icon = read_client_icon(parse_qs(parsed.query).get("id", [""])[0])
                self._write_bytes(200 if icon else 404, "image/png", icon)
                return
            if method == "GET" and parsed.path == self.server.dashboard_path:
                from audiagentic.components.agents.gateway.service.dashboard import (
                    render_dashboard_html,
                )

                self._write_bytes(200, "text/html; charset=utf-8", render_dashboard_html(self.server.dashboard_snapshot_path, focus_path=self.server.dashboard_focus_path, purge_session_path=self.server.dashboard_purge_session_path, focus_token=self.server.application.dashboard_action_token, complete_path=self.server.dashboard_complete_path))
                return
            if method == "GET" and parsed.path == self.server.dashboard_snapshot_path:
                query = parse_qs(parsed.query, keep_blank_values=True)
                raw_recent = query.get("recent-seconds", [None])[0]
                recent_seconds = _positive_int(raw_recent)
                self._write_json(
                    200,
                    self.server.application.dashboard_snapshot(recent_seconds=recent_seconds),
                )
                return
            if parsed.path == self.server.dashboard_image_path:
                if method == "GET":
                    project_id = parse_qs(parsed.query).get("project-id", [""])[0]
                    image = self.server.application.dashboard_project_image(project_id)
                    self._write_bytes(200 if image else 404, "image/png", image)
                    return
                self._authenticate_dashboard_action()
                body = self._read_body()
                if set(body) != {"project-id", "png"}:
                    raise transport_error(23, "project image body must contain project-id and png only")
                self.server.application.dashboard_project_image(_string(body, "project-id"), _string(body, "png"))
                self._write_json(200, {"ok": True})
                return
            if method == "GET" and parsed.path == self.server.dashboard_restart_path:
                self._authenticate_dashboard_action()
                health = self.server.application.health()
                self._write_json(200, {"state": health["state"], "owner-epoch": health["owner-epoch"]})
                return
            if method == "POST" and parsed.path == self.server.dashboard_restart_path:
                self._authenticate_dashboard_action()
                if self._read_body():
                    raise transport_error(23, "dashboard restart body must be empty")
                result = self.server.application.restart_dashboard_gateway()
                self._write_json(202, {"ok": True, "result": result})
                return
            if method == "POST" and parsed.path == self.server.dashboard_cancel_path:
                self._authenticate_dashboard_action()
                body = self._read_body()
                if set(body) != {"request-id"}:
                    raise transport_error(23, "dashboard cancel body must contain request-id only")
                result = self.server.application.cancel_dashboard_request(_string(body, "request-id"))
                self._write_json(200, {"ok": True, "result": result})
                return
            for route, shape, action in (
                (self.server.dashboard_close_session_path, {"project-id", "session-id"}, "close_dashboard_session"),
                (self.server.dashboard_archive_path, {"project-id", "request-id"}, "archive_dashboard_request"),
            ):
                if method == "POST" and parsed.path == route:
                    self._authenticate_dashboard_action()
                    body = self._read_body()
                    if set(body) != shape:
                        raise transport_error(23, f"dashboard action body must contain exactly {sorted(shape)}")
                    result = getattr(self.server.application, action)(*(_string(body, key) for key in sorted(shape)))
                    self._write_json(202 if action != "close_dashboard_session" else 200, {"ok": True, "result": result})
                    return
            if method == "POST" and parsed.path == self.server.dashboard_operation_path:
                self._authenticate_dashboard_action()
                body = self._read_body()
                if set(body) != {"operation-id"}:
                    raise transport_error(23, "dashboard operation status body must contain operation-id only")
                result = self.server.application.dashboard_operation_status(_string(body, "operation-id"))
                self._write_json(200, {"ok": True, "result": result})
                return
            if method == "POST" and parsed.path == self.server.dashboard_complete_path:
                self._authenticate_dashboard_action()
                body = self._read_body()
                if set(body) != {"request-id"}:
                    raise transport_error(23, "dashboard completion body must contain request-id only")
                result = self.server.application.complete_dashboard_request(_string(body, "request-id"))
                self._write_json(200, {"contract-version": "v1", "ok": True, "result": result})
                return
            if method == "POST" and parsed.path == self.server.dashboard_focus_path:
                self._authenticate_dashboard_action()
                body = self._read_body()
                if set(body) == {"session-id"}:
                    result = self.server.application.focus_dashboard_session(_string(body, "session-id"))
                elif set(body) == {"request-id"}:
                    result = self.server.application.focus_dashboard_request(_string(body, "request-id"))
                else:
                    raise transport_error(22, "dashboard focus body must contain session-id or request-id only")
                self._write_json(200, {"contract-version": "v1", "ok": True, "result": result})
                return
            if method == "POST" and parsed.path == self.server.dashboard_purge_session_path:
                self._authenticate_dashboard_action()
                body = self._read_body()
                if set(body) != {"session-id"}:
                    raise transport_error(23, "dashboard purge body must contain session-id only")
                result = self.server.application.purge_dashboard_session(_string(body, "session-id"))
                self._write_json(200, {"contract-version": "v1", "ok": True, "result": result})
                return
            self._authenticate()
            if method == "GET" and self.path == HEALTH_ROUTE:
                result = self.server.application.health()
            elif method == "POST" and self.path == CALL_ROUTE:
                body = self._read_body()
                result = self.server.application.invoke(
                    _string(body, "operation"),
                    _string(body, "project-root"),
                    _mapping(body.get("params"), "params"),
                    protocol_version=_string(body, "protocol-version"),
                    owner_epoch=_string(body, "owner-epoch"),
                    lease_id=_string(body, "lease-id"),
                )
            elif method == "POST" and self.path == LEASE_ACQUIRE_ROUTE:
                body = self._read_body()
                result = self.server.application.acquire_client(
                    _string(body, "client-instance-id"),
                    ttl_seconds=_number(body, "ttl-seconds"),
                    protocol_version=_string(body, "protocol-version"),
                    correlation_id=_optional_string(body, "correlation-id"),
                )
            elif method == "POST" and self.path == LEASE_RENEW_ROUTE:
                body = self._read_body()
                result = self.server.application.renew_client(
                    _string(body, "lease-id"),
                    ttl_seconds=_number(body, "ttl-seconds"),
                    owner_epoch=_string(body, "owner-epoch"),
                    protocol_version=_string(body, "protocol-version"),
                )
            elif method == "POST" and self.path == LEASE_RELEASE_ROUTE:
                body = self._read_body()
                result = self.server.application.release_client(
                    _string(body, "lease-id"),
                    owner_epoch=_string(body, "owner-epoch"),
                    protocol_version=_string(body, "protocol-version"),
                )
            else:
                raise transport_error(
                    4, "unknown gateway service route", method=method, path=self.path
                )
            self._write_json(200, {"contract-version": "v1", "ok": True, "result": result})
        except AudiaGenticError as exc:
            status = 401 if exc.code == "VAL-AGSV-005" else 400
            self._write_json(status, to_error_envelope(exc))
        except Exception:  # noqa: BLE001 - isolate the protocol boundary
            logger.exception(
                "gateway service request failed", extra={"method": method, "path": self.path}
            )
            self._write_json(
                500, to_error_envelope(internal_error(1, "gateway service request failed"))
            )

    def _authenticate(self) -> None:
        expected = f"Bearer {self.server.auth_token}"
        supplied = self.headers.get("Authorization", "")
        if not hmac.compare_digest(supplied, expected):
            raise transport_error(5, "gateway service authentication failed")

    def _dispatch_shared(self, method: str) -> None:
        ingress = self.server.shared_ingress
        assert ingress is not None
        authorizations = self.headers.get_all("Authorization", [])
        source_tokens = self.headers.get_all("X-AUDiaGentic-Source-Node-Token", [])
        if len(authorizations) != 1 or len(source_tokens) > 1:
            raise transport_error(22, "Shared authentication headers must be unique")
        if source_tokens and not (method == "POST" and self.path == "/shared/v1/call"):
            raise transport_error(22, "Source credentials are restricted to node submission")
        principal = ingress.authenticate(authorizations[0])
        if method == "GET" and self.path == "/shared/v1/health":
            result = ingress.health(self.server.application, principal)
        elif method == "POST" and self.path == "/shared/v1/call":
            body = self._read_body()
            lease_id, epoch = _string(body, "lease-id"), _string(body, "owner-epoch")
            client_id = self.server.application.require_client_principal(lease_id, epoch, principal.principal_id)
            operation, root, params = ingress.prepare_call(principal, body, client_instance_id=client_id)
            node_context = None
            if source_tokens or {"node_id", "workspace_id", "source_workspace"}.intersection(params):
                if operation != "submit_execution_request" or len(source_tokens) != 1:
                    raise transport_error(22, "Node submission requires one enrolled source credential")
                node_context, params = ingress.node_submission_context(
                    principal, body["project-id"], params, source_node_token=source_tokens[0],
                )
            result = self.server.application.invoke(
                operation, root, params,
                protocol_version=_string(body, "protocol-version"),
                owner_epoch=epoch, lease_id=lease_id,
                **({"node_context": node_context} if node_context is not None else {}),
            )
            # Compact only the shared wire boundary. Local HTTP and the Python
            # application retain their existing contracts; explicit reads of
            # diagnostics, evidence and response content are not projected here.
            from audiagentic.components.agents.gateway.evidence_projection import (
                project_public_gateway_request,
                project_public_gateway_session,
            )

            if operation in {
                "submit_execution_request", "cancel_execution_request",
                "recover_execution_request", "complete_execution_from_provider",
            }:
                result = project_public_gateway_request(result)
            elif operation in {"close_execution_session", "resume_execution_session"}:
                result = project_public_gateway_session(result)
            elif operation == "list_execution_sessions":
                result = [project_public_gateway_session(item) for item in result]
            # list_execution_requests already uses the canonical V4 status
            # projection in the API; preserve its lifecycle/activity fields.
        elif method == "POST" and self.path == "/shared/v1/client-leases/acquire":
            body = self._read_body()
            if body.keys() - {"client-instance-id", "ttl-seconds", "protocol-version", "correlation-id"}:
                raise transport_error(22, "Shared lease request contains invalid fields")
            # Client aliases cannot impersonate another authenticated principal.
            import hashlib

            client_id = hashlib.sha256(
                f"{principal.principal_id}:{_string(body, 'client-instance-id')}".encode()
            ).hexdigest()[:32]
            result = self.server.application.acquire_client(
                f"shared_{client_id}", ttl_seconds=_number(body, "ttl-seconds"),
                protocol_version=_string(body, "protocol-version"),
                correlation_id=_optional_string(body, "correlation-id"),
                facts={"shared-principal-id": principal.principal_id},
            )
        elif method == "POST" and self.path in {
            "/shared/v1/client-leases/renew", "/shared/v1/client-leases/release",
        }:
            body = self._read_body()
            renew = self.path.endswith("/renew")
            expected = {"lease-id", "owner-epoch", "protocol-version"} | ({"ttl-seconds"} if renew else set())
            if set(body) != expected:
                raise transport_error(22, "Shared lease request contains invalid fields")
            lease_id, epoch = _string(body, "lease-id"), _string(body, "owner-epoch")
            self.server.application.require_client_principal(lease_id, epoch, principal.principal_id)
            keywords = {"owner_epoch": epoch, "protocol_version": _string(body, "protocol-version")}
            if renew:
                result = self.server.application.renew_client(lease_id, ttl_seconds=_number(body, "ttl-seconds"), **keywords)
            else:
                result = self.server.application.release_client(lease_id, **keywords)
        else:
            raise transport_error(4, "Unknown shared gateway route")
        self._write_json(200, {"contract-version": "v1", "ok": True, "result": result})

    def _authenticate_dashboard_action(self) -> None:
        supplied = self.headers.get("X-AudiaGentic-Dashboard-Token", "")
        expected = self.server.application.dashboard_action_token
        origin = self.headers.get("Origin")
        if origin:
            host = self.headers.get("Host", "")
            if origin not in {f"http://{host}", f"https://{host}"}:
                raise transport_error(5, "dashboard action origin is invalid")
        if not supplied or not hmac.compare_digest(supplied, expected):
            raise transport_error(5, "dashboard action authentication failed")

    def _read_body(self) -> dict[str, Any]:
        raw_length = self.headers.get("Content-Length")
        try:
            length = int(raw_length or "")
        except ValueError as exc:
            raise transport_error(6, "gateway service content length is invalid") from exc
        if length <= 0 or length > MAX_REQUEST_BYTES:
            raise transport_error(6, "gateway service request body size is invalid", length=length)
        try:
            value = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise transport_error(7, "gateway service request body is invalid JSON") from exc
        if not isinstance(value, dict):
            raise transport_error(7, "gateway service request body must be a mapping")
        return cast(dict[str, Any], value)

    def _write_json(self, status: int, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
        self._write_bytes(status, "application/json", encoded)

    def _write_bytes(self, status: int, content_type: str, encoded: bytes) -> None:
        try:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(encoded)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            logger.debug("gateway client disconnected before response", extra={"path": self.path})

    def log_message(self, format: str, *args: Any) -> None:
        logger.debug(
            "gateway http request", extra={"client": self.client_address[0], "path": self.path}
        )


def _string(body: dict[str, Any], name: str) -> str:
    value = body.get(name)
    if not isinstance(value, str) or not value:
        raise transport_error(8, "gateway service string field is required", field=name)
    return value


def _optional_string(body: dict[str, Any], name: str) -> str | None:
    value = body.get(name)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise transport_error(8, "gateway service field must be a non-empty string", field=name)
    return value


def _number(body: dict[str, Any], name: str) -> float:
    value = body.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise transport_error(9, "gateway service numeric field must be positive", field=name)
    return value * 1.0


def _positive_int(value: object | None) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise transport_error(10, "gateway service field must be a mapping", field=name)
    return cast(dict[str, Any], value)


def _dashboard_path(value: str) -> str:
    if not value.startswith("/") or value == "/" or "?" in value or "#" in value:
        raise transport_error(18, "gateway dashboard path must be an absolute path", path=value)
    return value.rstrip("/")


__all__ = ["GatewayHTTPServer", "MAX_REQUEST_BYTES"]
