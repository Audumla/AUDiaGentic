"""JSON-RPC 2.0 stdio bridge for Language Server Protocol.

Launches a language server subprocess, frames requests with Content-Length
headers, and dispatches responses to awaiting futures.
"""

from __future__ import annotations

import json
import logging
import subprocess
import threading
import time
from collections.abc import Callable
from typing import IO, Any

from audiagentic.components.coding_lsp.lsp_constants import DEFAULT_TIMEOUT, METHOD_TIMEOUTS
from audiagentic.foundation.contracts.errors import AudiaGenticError, make_error
from audiagentic.foundation.system.supervised_process import (
    SupervisedProcess,
    spawn_supervised,
)

logger = logging.getLogger(__name__)

_LSP_CONTENT_HEADER = b"Content-Length:"
_CRLF = b"\r\n"

# EXT-LSP error code namespace
# EXT-LSP-001: LSP server returned an error response
# EXT-LSP-002: Language server process died unexpectedly
# EXT-LSP-003: Request timed out
# EXT-LSP-004: Server capability not supported
# EXT-LSP-005: Invalid position
# EXT-LSP-006: File not found
# EXT-LSP-007: No configured language server for file
# EXT-LSP-008: Server crashed mid-request
# EXT-LSP-009: Lost connection to language server


def _lsp_error(
    code: str, message: str, *, details: dict[str, Any] | None = None
) -> AudiaGenticError:
    """Construct a validated LSP error from the closed code vocabulary.

    Do not derive the public number by parsing caller input.  Each supported
    identity is declared as a literal construction so the conformance scan can
    prove that it is registered and unknown identities fail closed.
    """
    if code == "EXT-LSP-001":
        return make_error(prefix="EXT", component="LSP", number=1, kind="coding-lsp", message=message, details=details)
    if code == "EXT-LSP-002":
        return make_error(prefix="EXT", component="LSP", number=2, kind="coding-lsp", message=message, details=details)
    if code == "EXT-LSP-003":
        return make_error(prefix="EXT", component="LSP", number=3, kind="coding-lsp", message=message, details=details)
    if code == "EXT-LSP-004":
        return make_error(prefix="EXT", component="LSP", number=4, kind="coding-lsp", message=message, details=details)
    if code == "EXT-LSP-005":
        return make_error(prefix="EXT", component="LSP", number=5, kind="coding-lsp", message=message, details=details)
    if code == "EXT-LSP-006":
        return make_error(prefix="EXT", component="LSP", number=6, kind="coding-lsp", message=message, details=details)
    if code == "EXT-LSP-007":
        return make_error(prefix="EXT", component="LSP", number=7, kind="coding-lsp", message=message, details=details)
    if code == "EXT-LSP-008":
        return make_error(prefix="EXT", component="LSP", number=8, kind="coding-lsp", message=message, details=details)
    if code == "EXT-LSP-009":
        return make_error(prefix="EXT", component="LSP", number=9, kind="coding-lsp", message=message, details=details)
    raise ValueError(f"unsupported LSP error identity: {code!r}")


class LspJsonRpc:
    """JSON-RPC 2.0 client over stdio for LSP communication.

    Usage:
        bridge = LspJsonRpc()
        bridge.launch_server(["pyright-langserver", "--stdio"])
        future = bridge.send_request("initialize", params, id=1)
        response = future.result(timeout=10)
        bridge.shutdown()
    """

    def __init__(self) -> None:
        self._supervised: SupervisedProcess | None = None
        self._lock = threading.Lock()
        self._next_id = 0
        self._pending: dict[int, threading.Event] = {}
        self._responses: dict[int, dict[str, Any]] = {}
        self._reader_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self._running = False
        self._notification_handlers: dict[str, list[Callable]] = {}

    def launch_server(
        self, command: list[str], cwd: str | None = None, env: dict[str, str] | None = None
    ) -> None:
        """Launch a language server subprocess with stdio."""
        if self._supervised is not None and self._supervised.poll() is None:
            raise _lsp_error("EXT-LSP-002", "language server already running")
        self._supervised = spawn_supervised(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd,
            env=env,
            text=False,
        )
        self._running = True
        self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._reader_thread.start()
        self._stderr_thread = threading.Thread(target=self._stderr_drain, daemon=True)
        self._stderr_thread.start()

    def send_request(
        self, method: str, params: Any, id: int | None = None, timeout: float | None = None
    ) -> Any:
        """Send a JSON-RPC request and block until response.

        Returns the result from `result` field of response.
        Raises AudiaGenticError (EXT-LSP-001) if server returns an error.
        Raises AudiaGenticError (EXT-LSP-002) if process died.
        Raises AudiaGenticError (EXT-LSP-003) on timeout.
        """
        if id is None:
            with self._lock:
                self._next_id += 1
                id = self._next_id
        if timeout is None:
            timeout = METHOD_TIMEOUTS.get(method, DEFAULT_TIMEOUT)

        max_retries = 3
        attempt = 0
        while True:
            attempt += 1
            event = threading.Event()
            req_id = id + attempt - 1
            with self._lock:
                self._pending[req_id] = event
            msg = {"jsonrpc": "2.0", "method": method, "params": params, "id": req_id}
            start = time.monotonic()
            try:
                self._write_message(msg)
                if not event.wait(timeout):
                    self._send_cancel(req_id)
                    raise _lsp_error(
                        "EXT-LSP-003",
                        f"LSP request '{method}' timed out after {timeout}s",
                        details={"method": method, "timeout_s": timeout, "request_id": id},
                    )
                with self._lock:
                    response = self._responses.pop(req_id, None)
                if response is None:
                    raise _lsp_error(
                        "EXT-LSP-008", f"No response for request {id}; server likely crashed"
                    )
                if "error" in response:
                    err = response["error"]
                    lsp_code = err.get("code", -1)
                    lsp_message = err.get("message", "unknown")
                    should_retry = attempt <= max_retries and (
                        (lsp_code == -32801 and "cargo metadata" in lsp_message)
                        or (lsp_code == -32801 and "content modified" in lsp_message)
                        or (lsp_code == -32602 and "No references found" in lsp_message)
                    )
                    if should_retry:
                        logger.debug(
                            "Server indexing, retrying %s (attempt %d/%d)",
                            method,
                            attempt,
                            max_retries,
                        )
                        time.sleep(1.0 * attempt)
                        continue
                    raise _lsp_error(
                        "EXT-LSP-001",
                        f"LSP error {lsp_code}: {lsp_message}",
                        details={
                            "lsp-code": lsp_code,
                            "lsp-message": lsp_message,
                            "data": err.get("data"),
                        },
                    )
                return response.get("result")
            finally:
                with self._lock:
                    self._pending.pop(req_id, None)
                elapsed_ms = (time.monotonic() - start) * 1000
                logger.debug("LSP %s took %.1fms", method, elapsed_ms)

    def _send_cancel(self, request_id: int) -> None:
        """Send $/cancelRequest to stop an abandoned in-flight request."""
        cancel = {"jsonrpc": "2.0", "method": "$/cancelRequest", "params": {"id": request_id}}
        try:
            self._write_message(cancel)
        except Exception:
            logger.debug("Failed to send $/cancelRequest for %d", request_id, exc_info=True)

    def _fail_all_pending(self) -> None:
        """Fail all in-flight requests with a crashed-server envelope."""
        with self._lock:
            for rid, ev in self._pending.items():
                self._responses[rid] = {
                    "jsonrpc": "2.0",
                    "id": rid,
                    "error": {"code": -1, "message": "server crashed"},
                }
                ev.set()

    def send_notification(self, method: str, params: Any) -> None:
        """Send a JSON-RPC notification (no response expected)."""
        msg = {"jsonrpc": "2.0", "method": method, "params": params}
        self._write_message(msg)

    def on_notification(self, method: str, handler: Callable) -> None:
        """Register a callback for an incoming server→client notification."""
        self._notification_handlers.setdefault(method, []).append(handler)

    def _reply_to_server_request(self, msg_id: int, result: Any) -> None:
        """Send a JSON-RPC response for a server→client request."""
        response = {"jsonrpc": "2.0", "id": msg_id, "result": result}
        self._write_message(response)

    def _handle_server_request(self, msg: dict[str, Any]) -> None:
        """Handle an inbound server→client request."""
        msg_id = msg.get("id")
        if msg_id is None:
            return
        method = msg.get("method", "")

        if method == "workspace/configuration":
            params = msg.get("params", {})
            items = params.get("items", [])
            self._reply_to_server_request(
                int(msg_id), [item.get("defaultItem", {}) for item in items]
            )
        elif method == "client/registerCapability":
            self._reply_to_server_request(int(msg_id), {"registrations": []})
        else:
            logger.debug("Unhandled server request: %s", method)
            self._reply_to_server_request(int(msg_id), None)

    def is_alive(self) -> bool:
        """Return True if the language server process is running."""
        if self._supervised is None:
            return False
        return self._supervised.poll() is None

    def shutdown(self) -> None:
        """Graceful LSP shutdown: send shutdown + exit, then kill if needed."""
        if self._supervised is None or self._supervised.poll() is not None:
            return
        try:
            self.send_request("shutdown", None, timeout=5)
            self.send_notification("exit", None)
            self._running = False
            self._supervised.wait(timeout=5)
        except (TimeoutError, OSError, AudiaGenticError):
            try:
                self._running = False
            finally:
                # SupervisedProcess.close() handles tree teardown
                self._supervised.close()
        self._supervised = None

    # ── internal ──────────────────────────────────────────────────────────

    def _write_message(self, obj: dict[str, Any]) -> None:
        if self._supervised is None or self._supervised.poll() is not None:
            raise _lsp_error("EXT-LSP-002", "Language server process is not running")
        stdin = self._supervised.process.stdin
        if stdin is None:
            raise _lsp_error("EXT-LSP-002", "Language server stdin is not available")
        payload = json.dumps(obj, separators=(",", ":")).encode("utf-8")
        header = f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii")
        try:
            stdin.write(header + payload)
            stdin.flush()
        except (BrokenPipeError, OSError):
            raise _lsp_error("EXT-LSP-009", "Lost connection to language server")

    def _reader_loop(self) -> None:
        if self._supervised is None:
            return
        try:
            while self._running:
                msg = self._read_message()
                if msg is None:
                    break

                msg_id = msg.get("id")
                method = msg.get("method")

                if method and msg_id is not None:
                    self._handle_server_request(msg)
                elif method and msg_id is None:
                    handlers = self._notification_handlers.get(method, [])
                    for handler in handlers:
                        try:
                            handler(msg.get("params"))
                        except Exception:
                            logger.error("Notification handler error for %s", method, exc_info=True)
                elif msg_id is not None and msg_id in self._pending:
                    with self._lock:
                        self._responses[msg_id] = msg
                        self._pending[msg_id].set()
                else:
                    logger.debug("Dropping unhandled LSP message: method=%s id=%s", method, msg_id)
        except Exception:
            logger.error("LSP bridge reader thread exited unexpectedly", exc_info=True)
            self._fail_all_pending()

    def _read_message(self) -> dict[str, Any] | None:
        proc = self._supervised.process if self._supervised is not None else None
        if proc is None:
            return None
        stdout = proc.stdout
        if stdout is None:
            return None
        header = self._read_header(stdout)
        if header is None:
            return None
        content_length = self._parse_content_length(header)
        if content_length is None:
            return None
        body = self._read_exact(stdout, content_length)
        if body is None:
            return None
        try:
            return json.loads(body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise _lsp_error("EXT-LSP-002", f"Invalid JSON-RPC message: {exc}")

    def _read_header(self, stream: IO[bytes]) -> bytes | None:
        header_parts: list[bytes] = []
        while True:
            line = self._read_line(stream)
            if line is None:
                return None
            header_parts.append(line)
            if line in (b"\r\n", b"\n", b""):
                return b"".join(header_parts)

    def _read_line(self, stream: IO[bytes]) -> bytes | None:
        try:
            return stream.readline()
        except OSError:
            return None

    def _stderr_drain(self) -> None:
        """Drain server stderr to debug log to prevent pipe-buffer deadlock."""
        proc = self._supervised.process if self._supervised is not None else None
        if proc is None or proc.stderr is None:
            return
        try:
            for line in iter(proc.stderr.readline, b""):
                if not self._running:
                    break
                decoded = line.decode("utf-8", errors="replace").rstrip()
                if decoded:
                    logger.debug("[lsp-stderr] %s", decoded)
        except OSError:
            pass

    def _read_exact(self, stream: IO[bytes], length: int) -> bytes | None:
        data = bytearray()
        while len(data) < length:
            chunk = stream.read(min(length - len(data), 65536))
            if not chunk:
                return None
            data.extend(chunk)
        return bytes(data)

    def _parse_content_length(self, header: bytes) -> int | None:
        try:
            header_str = header.decode("ascii", errors="ignore")
            for line in header_str.split("\r\n"):
                if line.lower().startswith("content-length:"):
                    return int(line.split(":", 1)[1].strip())
        except (ValueError, UnicodeDecodeError):
            pass
        return None

    def __del__(self) -> None:
        if self._supervised is not None and self._supervised.poll() is None:
            try:
                close = getattr(self._supervised, "close", None)
                if callable(close):
                    close()
            except (OSError, TypeError):
                pass

