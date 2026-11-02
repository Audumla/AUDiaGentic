"""OpenCode v2 server native client and join adapter declaration (SH56).

``opencode serve`` exposes a session HTTP API (``/api/session``, ``/prompt``, ``/inbox``, ``/message``, ``/event``)
guarded by HTTP Basic auth with ``OPENCODE_SERVER_PASSWORD``. This module is the one place that speaks it. The
prompt route takes ``delivery``: ``queue`` durably enqueues the prompt behind the active turn, ``steer`` injects it
into the running loop, and the server's own default is ``steer``, so ``OpenCodeClient.prompt`` always sends ``delivery: queue`` and offers no other mode.
``JOIN_ADAPTER`` is the identity qualification evidence is bound to (its source file's digest).
"""
from __future__ import annotations

import base64
import json
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from audiagentic.components.providers.services.session.join_readiness import JoinAdapterInfo
from audiagentic.foundation.system.process import terminate_process_group

NATIVE_SCHEMA_VERSION = "opencode-api-v2"
JOIN_ADAPTER = JoinAdapterInfo(adapter_id="opencode-serve", adapter_version="1", native_schema_version=NATIVE_SCHEMA_VERSION)
QUEUE_DELIVERY = "queue"
REQUIRED_PATHS = frozenset({"/api/session", "/api/session/{sessionID}/prompt", "/api/session/{sessionID}/inbox",
                            "/api/session/{sessionID}/message", "/api/event"})


class OpenCodeError(RuntimeError):
    def __init__(self, kind: str, what: str, status: int | None = None) -> None:
        super().__init__(f"{kind}: {what}" + (f" ({status})" if status else ""))
        self.kind, self.what, self.status = kind, what, status


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


class OpenCodeClient:
    """One HTTP client of a running ``opencode serve``; holds no session state, so a "detach" is just stopping."""

    def __init__(self, port: int, password: str, *, timeout: float = 20.0) -> None:
        token = base64.b64encode(f"opencode:{password}".encode()).decode()
        self._base, self._headers, self._timeout = f"http://127.0.0.1:{port}", {"Authorization": f"Basic {token}"}, timeout

    def call(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        request = urllib.request.Request(
            self._base + path, method=method, headers={**self._headers, "content-type": "application/json"},
            data=json.dumps(body).encode() if body is not None else None)
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:  # noqa: S310 - loopback only
                payload = json.loads(response.read() or b"null")
        except urllib.error.HTTPError as error:
            raise OpenCodeError("http", f"{method} {path}", error.code) from None
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise OpenCodeError("unreachable", f"{method} {path}") from error
        return payload.get("data") if isinstance(payload, dict) and "data" in payload else payload

    def openapi_paths(self) -> set[str]:
        return set((self.call("GET", "/openapi.json") or {}).get("paths", {}))

    def create_session(self, title: str, provider: str, model: str) -> str:
        return str(self.call("POST", "/api/session", {"title": title, "model": {"providerID": provider, "id": model}})["id"])

    def prompt(self, session_id: str, text: str, *, message_id: str | None = None) -> dict[str, Any]:
        """Queue a prompt behind the session's active turn. Delivery is fixed to ``queue``: it is the only mode whose
        busy-turn behaviour was measured, and the server's own default (``steer``) injects into a running turn."""
        body: dict[str, Any] = {"text": text, "delivery": QUEUE_DELIVERY}
        if message_id:
            body["id"] = message_id
        return self.call("POST", f"/api/session/{session_id}/prompt", body)

    def sessions(self) -> list[dict[str, Any]]:
        return list(self.call("GET", "/api/session") or [])

    def messages(self, session_id: str) -> list[dict[str, Any]]:
        return list(self.call("GET", f"/api/session/{session_id}/message") or [])

    def inbox(self, session_id: str) -> list[dict[str, Any]]:
        return list(self.call("GET", f"/api/session/{session_id}/inbox") or [])

    def active(self) -> dict[str, Any]:
        return dict(self.call("GET", "/api/session/active") or {})


class OwnedOpenCodeServer:
    """An ``opencode serve`` this caller started on a free loopback port, stopped by its exact process group."""

    def __init__(self, env: dict[str, str], cwd: Path) -> None:
        self._env, self._cwd = env, cwd
        self.port = free_port()
        self.process: subprocess.Popen[bytes] | None = None

    def start(self, password_probe: Any, timeout: float = 40.0) -> OwnedOpenCodeServer:
        self.process = subprocess.Popen(  # noqa: S603 - fixed argv, scrubbed environment
            ["opencode", "serve", "--hostname", "127.0.0.1", "--port", str(self.port)], env=self._env, cwd=self._cwd,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if self.process.poll() is not None:
                raise OpenCodeError("exited", "serve", self.process.returncode)
            try:
                password_probe()
                return self
            except OpenCodeError:
                time.sleep(0.5)
        self.stop()
        raise OpenCodeError("timeout", "serve")

    @property
    def alive(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def stop(self) -> bool:
        if self.process is None:
            return True
        terminate_process_group(self.process, term_wait=8)
        return self.process.poll() is not None
