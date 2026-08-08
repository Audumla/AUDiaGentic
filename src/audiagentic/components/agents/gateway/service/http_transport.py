"""Authenticated loopback HTTP adapter for the standalone gateway service."""

from __future__ import annotations

import hmac
import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, cast

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
    ) -> None:
        if address[0] != "127.0.0.1":
            raise transport_error(3, "gateway service must bind to IPv4 loopback")
        self.application = application
        self.auth_token = auth_token
        super().__init__(address, GatewayHTTPRequestHandler)


class GatewayHTTPRequestHandler(BaseHTTPRequestHandler):
    server: GatewayHTTPServer  # pyright: ignore[reportIncompatibleVariableOverride]

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
        self._dispatch("GET")

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
        self._dispatch("POST")

    def _dispatch(self, method: str) -> None:
        try:
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
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
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


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise transport_error(10, "gateway service field must be a mapping", field=name)
    return cast(dict[str, Any], value)


__all__ = ["GatewayHTTPServer", "MAX_REQUEST_BYTES"]
