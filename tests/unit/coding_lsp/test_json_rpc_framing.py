from __future__ import annotations

import io
import json
import subprocess

import pytest

from audiagentic.components.optional.coding_lsp.lsp_bridge import (
    LspJsonRpc,
)


class _MockLspServer:
    """Fake LSP server that echoes requests as responses."""

    def __init__(self, delay: float = 0.0, fail_after: int = 0) -> None:
        self.delay = delay
        self.fail_after = fail_after
        self.request_count = 0

    def run(self, stdin: subprocess.PIPE, stdout: subprocess.PIPE) -> None:
        self._stdin = stdin
        self._stdout = stdout
        header_buf = bytearray()
        content_length: int | None = None
        while True:
            byte = stdin.read(1)
            if not byte:
                break
            header_buf.extend(byte)
            if b"\r\n\r\n" in header_buf:
                header_part, header_buf = header_buf.split(b"\r\n\r\n", 1)
                for line in header_part.decode("ascii", errors="ignore").split("\r\n"):
                    if line.lower().startswith("content-length:"):
                        content_length = int(line.split(":", 1)[1].strip())
                if content_length is not None:
                    body = bytearray()
                    while len(body) < content_length:
                        chunk = stdin.read(min(content_length - len(body), 4096))
                        if not chunk:
                            break
                        body.extend(chunk)
                    if body:
                        self._handle_message(json.loads(body.decode("utf-8")))
                    content_length = None

    def _handle_message(self, msg: dict) -> None:
        self.request_count += 1
        rid = msg.get("id")
        if rid is not None:
            if self.fail_after and self.request_count >= self.fail_after:
                resp = {"jsonrpc": "2.0", "id": rid, "error": {"code": -32603, "message": "internal error"}}
            else:
                resp = {"jsonrpc": "2.0", "id": rid, "result": {"echo": msg.get("method")}}
            payload = json.dumps(resp, separators=(",", ":")).encode("utf-8")
            header = f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii")
            self._stdout.write(header + payload)
            self._stdout.flush()


def test_launch_and_shutdown() -> None:
    bridge = LspJsonRpc()
    bridge._process = None
    assert not bridge.is_alive()
    bridge.shutdown()


def test_write_message_frames_correctly() -> None:
    bridge = LspJsonRpc()
    fake_stdin: list[bytes] = []

    class FakeProcess:
        def poll(self):
            return None
        stdin = type("SI", (), {"write": lambda s, d: fake_stdin.append(d), "flush": lambda s: None})()

    bridge._process = FakeProcess()  # type: ignore[assignment]
    bridge._write_message({"jsonrpc": "2.0", "method": "test", "id": 1})
    raw = fake_stdin[0]
    assert b"Content-Length:" in raw
    header_end = raw.index(b"\r\n\r\n") + 4
    body = raw[header_end:]
    msg = json.loads(body)
    assert msg["method"] == "test"
    assert msg["id"] == 1


def test_parse_content_length() -> None:
    bridge = LspJsonRpc()
    assert bridge._parse_content_length(b"Content-Length: 42\r\n\r\n") == 42
    assert bridge._parse_content_length(b"content-length: 100\r\n\r\n") == 100
    assert bridge._parse_content_length(b"Content-Length: 0\r\n\r\n") == 0
    assert bridge._parse_content_length(b"Garbage\r\n\r\n") is None


def test_read_header_stops_on_blank_crlf_line() -> None:
    bridge = LspJsonRpc()
    stream = io.BytesIO(b"Content-Length: 2\r\n\r\n{}")
    header = bridge._read_header(stream)
    assert header == b"Content-Length: 2\r\n\r\n"


def test_send_request_registers_pending_before_write(monkeypatch) -> None:
    bridge = LspJsonRpc()

    def _fake_write(_msg):
        rid = 1
        with bridge._lock:
            assert rid in bridge._pending
            bridge._responses[rid] = {"jsonrpc": "2.0", "id": rid, "result": {"ok": True}}
            bridge._pending[rid].set()

    monkeypatch.setattr(bridge, "_write_message", _fake_write)
    result = bridge.send_request("initialize", {}, id=1, timeout=0.1)
    assert result == {"ok": True}


def test_shutdown_sends_request_then_exit(monkeypatch) -> None:
    bridge = LspJsonRpc()
    calls: list[tuple[str, str]] = []

    class FakeProcess:
        def poll(self):
            return None
        def wait(self, timeout=None):
            return 0

    bridge._process = FakeProcess()  # type: ignore[assignment]
    bridge._running = True

    monkeypatch.setattr(bridge, "send_request", lambda method, params, id=None, timeout=30.0: calls.append(("request", method)) or {})
    monkeypatch.setattr(bridge, "send_notification", lambda method, params: calls.append(("notification", method)))

    bridge.shutdown()

    assert calls == [("request", "shutdown"), ("notification", "exit")]


@pytest.mark.skip(reason="requires real pyright-langserver binary")
def test_real_pyright_lifecycle():
    bridge = LspJsonRpc()
    try:
        bridge.launch_server(["pyright-langserver", "--stdio"])
        assert bridge.is_alive()
        result = bridge.send_request(
            "initialize",
            {
                "processId": None,
                "rootUri": None,
                "capabilities": {},
            },
            timeout=15,
        )
        assert "capabilities" in result
    finally:
        bridge.shutdown()
