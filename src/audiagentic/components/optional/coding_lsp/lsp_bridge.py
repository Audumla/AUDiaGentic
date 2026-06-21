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
from typing import Any, Callable

from audiagentic.foundation.contracts.errors import AudiaGenticError, make_error

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


def _lsp_error(code: str, message: str, *, details: dict[str, Any] | None = None) -> AudiaGenticError:
    """Construct a validated LSP error using the canonical make_error factory."""
    return make_error(
        prefix="EXT",
        component="LSP",
        number=int(code.split("-")[-1]),
        kind="coding-lsp",
        message=message,
        details=details,
    )


# Method→timeout map (performance budgets from plan)
_METHOD_TIMEOUTS: dict[str, float] = {
    # File-level queries
    "textDocument/definition": 3.0,
    "textDocument/hover": 3.0,
    "textDocument/references": 3.0,
    "textDocument/typeDefinition": 3.0,
    "textDocument/implementation": 3.0,
    "textDocument/documentSymbol": 3.0,
    "textDocument/codeAction": 3.0,
    "textDocument/formatting": 3.0,
    "textDocument/rangeFormatting": 3.0,
    "textDocument/rename": 3.0,
    "textDocument/completion": 3.0,
    "textDocument/signatureHelp": 3.0,
    "textDocument/inlayHint": 3.0,
    # Workspace-level queries
    "workspace/symbol": 8.0,
    "workspace/diagnostic": 30.0,
    "workspace/configuration": 5.0,
    # Lifecycle
    "initialize": 30.0,
    "shutdown": 5.0,
}
_DEFAULT_TIMEOUT = 30.0


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
        self._process: subprocess.Popen[bytes] | None = None
        self._lock = threading.Lock()
        self._next_id = 0
        self._pending: dict[int, threading.Event] = {}
        self._responses: dict[int, dict[str, Any]] = {}
        self._reader_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self._running = False
        self._notification_handlers: dict[str, list[Callable]] = {}

    def launch_server(self, command: list[str], cwd: str | None = None, env: dict[str, str] | None = None) -> None:
        """Launch a language server subprocess with stdio."""
        if self._process is not None and self._process.poll() is None:
            raise _lsp_error("EXT-LSP-002", "language server already running")
        self._process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd,
            env=env,
        )
        self._running = True
        self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._reader_thread.start()
        self._stderr_thread = threading.Thread(target=self._stderr_drain, daemon=True)
        self._stderr_thread.start()

    def send_request(self, method: str, params: Any, id: int | None = None, timeout: float | None = None) -> Any:
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
            timeout = _METHOD_TIMEOUTS.get(method, _DEFAULT_TIMEOUT)
        event = threading.Event()
        with self._lock:
            self._pending[id] = event
        msg = {"jsonrpc": "2.0", "method": method, "params": params, "id": id}
        start = time.monotonic()
        try:
            self._write_message(msg)
            if not event.wait(timeout):
                self._send_cancel(id)
                raise _lsp_error(
                    "EXT-LSP-003",
                    f"LSP request '{method}' timed out after {timeout}s",
                    details={"method": method, "timeout_s": timeout, "request_id": id},
                )
            with self._lock:
                response = self._responses.pop(id, None)
            if response is None:
                raise _lsp_error("EXT-LSP-008", f"No response for request {id}; server likely crashed")
            if "error" in response:
                err = response["error"]
                lsp_code = err.get("code", -1)
                lsp_message = err.get("message", "unknown")
                raise _lsp_error(
                    "EXT-LSP-001",
                    f"LSP error {lsp_code}: {lsp_message}",
                    details={"lsp-code": lsp_code, "lsp-message": lsp_message, "data": err.get("data")},
                )
            return response.get("result")
        finally:
            with self._lock:
                self._pending.pop(id, None)
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
            self._reply_to_server_request(int(msg_id), [item.get("defaultItem", {}) for item in items])
        elif method == "client/registerCapability":
            self._reply_to_server_request(int(msg_id), {"registrations": []})
        else:
            logger.debug("Unhandled server request: %s", method)
            self._reply_to_server_request(int(msg_id), None)

    def is_alive(self) -> bool:
        """Return True if the language server process is running."""
        if self._process is None:
            return False
        return self._process.poll() is None

    def shutdown(self) -> None:
        """Graceful LSP shutdown: send shutdown + exit, then kill if needed."""
        if self._process is None or self._process.poll() is not None:
            return
        try:
            self.send_request("shutdown", None, timeout=5)
            self.send_notification("exit", None)
            self._running = False
            self._process.wait(timeout=5)
        except (TimeoutError, OSError, AudiaGenticError):
            try:
                self._running = False
                self._process.kill()
                self._process.wait(timeout=3)
            except (OSError, TimeoutError):
                pass
        self._process = None

    # ── internal ──────────────────────────────────────────────────────────

    def _write_message(self, obj: dict[str, Any]) -> None:
        if self._process is None or self._process.poll() is not None:
            raise _lsp_error("EXT-LSP-002", "Language server process is not running")
        payload = json.dumps(obj, separators=(",", ":")).encode("utf-8")
        header = f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii")
        try:
            self._process.stdin.write(header + payload)
            self._process.stdin.flush()
        except (BrokenPipeError, OSError):
            raise _lsp_error("EXT-LSP-009", "Lost connection to language server")

    def _reader_loop(self) -> None:
        if self._process is None:
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
        if self._process is None:
            return None
        stdout = self._process.stdout
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

    def _read_header(self, stream: subprocess.PIPE) -> bytes | None:
        header_parts: list[bytes] = []
        while True:
            line = self._read_line(stream)
            if line is None:
                return None
            header_parts.append(line)
            if line in (b"\r\n", b"\n", b""):
                return b"".join(header_parts)

    def _read_line(self, stream: subprocess.PIPE) -> bytes | None:
        try:
            return stream.readline()
        except OSError:
            return None

    def _stderr_drain(self) -> None:
        """Drain server stderr to debug log to prevent pipe-buffer deadlock."""
        if self._process is None or self._process.stderr is None:
            return
        try:
            for line in iter(self._process.stderr.readline, b""):
                if not self._running:
                    break
                decoded = line.decode("utf-8", errors="replace").rstrip()
                if decoded:
                    logger.debug("[lsp-stderr] %s", decoded)
        except OSError:
            pass

    def _read_exact(self, stream: subprocess.PIPE, length: int) -> bytes | None:
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
        if self._process is not None and isinstance(self._process, subprocess.Popen) and self._process.poll() is None:
            try:
                self._process.terminate()
            except OSError:
                pass
