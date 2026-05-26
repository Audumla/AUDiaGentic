"""JSON-RPC 2.0 stdio bridge for Language Server Protocol.

Launches a language server subprocess, frames requests with Content-Length
headers, and dispatches responses to awaiting futures.
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import threading
import time
from collections.abc import Awaitable
from typing import Any

_LSP_CONTENT_HEADER = b"Content-Length:"
_CRLF = b"\r\n"


class LspError(Exception):
    """Raised when the LSP server returns an error code."""

    def __init__(self, code: int, message: str, data: Any = None) -> None:
        self.code = code
        self.message = message
        self.data = data
        super().__init__(f"LSP error {code}: {message}")


class LspServerError(Exception):
    """Raised when the language server process dies unexpectedly."""


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
        self._running = False

    def launch_server(self, command: list[str], cwd: str | None = None, env: dict[str, str] | None = None) -> None:
        """Launch a language server subprocess with stdio."""
        if self._process is not None and self._process.poll() is None:
            raise RuntimeError("Server already running")
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

    def send_request(self, method: str, params: Any, id: int | None = None, timeout: float = 30.0) -> Any:
        """Send a JSON-RPC request and block until response.

        Returns the result from `result` field of response.
        Raises LspError if server returns an error.
        Raises LspServerError if process died.
        """
        if id is None:
            with self._lock:
                self._next_id += 1
                id = self._next_id
        msg = {"jsonrpc": "2.0", "method": method, "params": params, "id": id}
        self._write_message(msg)
        event = threading.Event()
        with self._lock:
            self._pending[id] = event
        try:
            if not event.wait(timeout):
                raise TimeoutError(f"LSP request '{method}' timed out after {timeout}s")
            with self._lock:
                response = self._responses.pop(id, None)
            if response is None:
                raise LspServerError(f"No response for request {id}")
            if "error" in response:
                err = response["error"]
                raise LspError(err.get("code", -1), err.get("message", "unknown"), err.get("data"))
            return response.get("result")
        finally:
            with self._lock:
                self._pending.pop(id, None)

    def send_notification(self, method: str, params: Any) -> None:
        """Send a JSON-RPC notification (no response expected)."""
        msg = {"jsonrpc": "2.0", "method": method, "params": params}
        self._write_message(msg)

    def is_alive(self) -> bool:
        """Return True if the language server process is running."""
        if self._process is None:
            return False
        return self._process.poll() is None

    def shutdown(self) -> None:
        """Graceful LSP shutdown: send shutdown + exit, then kill if needed."""
        self._running = False
        if self._process is None or self._process.poll() is not None:
            return
        try:
            self.send_notification("shutdown", None)
            self.send_notification("exit", None)
            self._process.wait(timeout=5)
        except (TimeoutError, OSError, LspError):
            try:
                self._process.kill()
                self._process.wait(timeout=3)
            except (OSError, TimeoutError):
                pass
        self._process = None

    # ── internal ──────────────────────────────────────────────────────────

    def _write_message(self, obj: dict[str, Any]) -> None:
        if self._process is None or self._process.poll() is not None:
            raise LspServerError("Language server process is not running")
        payload = json.dumps(obj, separators=(",", ":")).encode("utf-8")
        header = f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii")
        try:
            self._process.stdin.write(header + payload)
            self._process.stdin.flush()
        except (BrokenPipeError, OSError):
            raise LspServerError("Lost connection to language server")

    def _reader_loop(self) -> None:
        if self._process is None:
            return
        try:
            while self._running:
                msg = self._read_message()
                if msg is None:
                    break
                rid = msg.get("id")
                if rid is not None and rid in self._pending:
                    with self._lock:
                        self._responses[rid] = msg
                        self._pending[rid].set()
        except Exception:
            if self._process and self._process.poll() is not None:
                with self._lock:
                    for ev in self._pending.values():
                        ev.set()
                    self._responses.clear()

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
            raise LspServerError(f"Invalid JSON-RPC message: {exc}")

    def _read_header(self, stream: subprocess.PIPE) -> bytes | None:
        header_parts: list[bytes] = []
        while True:
            line = self._read_line(stream)
            if line is None:
                return None
            header_parts.append(line)
            if line == b"\r\n" or line == b"":
                return b"".join(header_parts)

    def _read_line(self, stream: subprocess.PIPE) -> bytes | None:
        try:
            byte = stream.read(1)
            if not byte:
                return None
            line = bytearray()
            while byte != b"\n" and byte:
                line.extend(byte)
                byte = stream.read(1)
            return bytes(line)
        except (OSError, IOError):
            return None

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
