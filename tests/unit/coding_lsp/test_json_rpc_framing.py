from __future__ import annotations

import io
import json
import shutil
from typing import IO

import pytest

from audiagentic.components.coding_lsp.lsp_bridge import (
    LspJsonRpc,
)


class _MockLspServer:
    """Fake LSP server that echoes requests as responses."""

    def __init__(self, delay: float = 0.0, fail_after: int = 0) -> None:
        self.delay = delay
        self.fail_after = fail_after
        self.request_count = 0

    def run(self, stdin: IO[bytes], stdout: IO[bytes]) -> None:
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


@pytest.mark.skipif(shutil.which("pyright-langserver") is None, reason="pyright-langserver not on PATH")
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


def test_on_notification_registers_handler() -> None:
    bridge = LspJsonRpc()
    received: list[dict] = []
    bridge.on_notification("textDocument/publishDiagnostics", lambda p: received.append(p))
    assert "textDocument/publishDiagnostics" in bridge._notification_handlers
    assert len(bridge._notification_handlers["textDocument/publishDiagnostics"]) == 1


def test_on_notification_multiple_handlers() -> None:
    bridge = LspJsonRpc()
    r1: list[dict] = []
    r2: list[dict] = []
    bridge.on_notification("test/notif", lambda p: r1.append(p))
    bridge.on_notification("test/notif", lambda p: r2.append(p))
    assert len(bridge._notification_handlers["test/notif"]) == 2


def _fake_process():
    class FP:
        def poll(self):
            return None
    return FP()  # type: ignore[return-value]


def test_reader_loop_dispatches_notification(monkeypatch) -> None:
    bridge = LspJsonRpc()
    bridge._process = _fake_process()  # type: ignore[assignment]
    received: list[dict] = []
    bridge.on_notification("textDocument/publishDiagnostics", lambda p: received.append(p))

    messages = [
        {"jsonrpc": "2.0", "method": "textDocument/publishDiagnostics", "params": {"uri": "file://test.py", "diagnostics": []}},
    ]
    msg_count = [0]

    def fake_read():
        if msg_count[0] < len(messages):
            msg_count[0] += 1
            return messages[msg_count[0] - 1]
        return None

    monkeypatch.setattr(bridge, "_read_message", fake_read)
    bridge._running = True
    bridge._reader_loop()
    assert len(received) == 1
    assert received[0]["uri"] == "file://test.py"


def test_reader_loop_handles_server_request_workspace_config(monkeypatch) -> None:
    bridge = LspJsonRpc()
    bridge._process = _fake_process()  # type: ignore[assignment]
    sent_messages: list[dict] = []
    monkeypatch.setattr(bridge, "_write_message", lambda m: sent_messages.append(m))

    server_request = {
        "jsonrpc": "2.0",
        "id": 99,
        "method": "workspace/configuration",
        "params": {"items": [{"section": "python", "defaultItem": {"analysis": {}}}]},
    }

    call_count = [0]
    def stopping_read():
        call_count[0] += 1
        if call_count[0] == 1:
            return server_request
        return None

    monkeypatch.setattr(bridge, "_read_message", stopping_read)
    bridge._running = True
    bridge._reader_loop()
    assert len(sent_messages) == 1
    assert sent_messages[0]["id"] == 99
    assert sent_messages[0]["result"] == [{"analysis": {}}]


def test_reader_loop_handles_server_request_register_capability(monkeypatch) -> None:
    bridge = LspJsonRpc()
    bridge._process = _fake_process()  # type: ignore[assignment]
    sent_messages: list[dict] = []
    monkeypatch.setattr(bridge, "_write_message", lambda m: sent_messages.append(m))

    server_request = {
        "jsonrpc": "2.0",
        "id": 100,
        "method": "client/registerCapability",
        "params": {"registrations": []},
    }

    call_count = [0]
    def stopping_read():
        call_count[0] += 1
        if call_count[0] == 1:
            return server_request
        return None

    monkeypatch.setattr(bridge, "_read_message", stopping_read)
    bridge._running = True
    bridge._reader_loop()
    assert len(sent_messages) == 1
    assert sent_messages[0]["id"] == 100
    assert sent_messages[0]["result"] == {"registrations": []}


def test_reader_loop_drops_unhandled_message(monkeypatch, caplog) -> None:
    bridge = LspJsonRpc()
    bridge._process = _fake_process()  # type: ignore[assignment]
    sent_messages: list[dict] = []
    monkeypatch.setattr(bridge, "_write_message", lambda m: sent_messages.append(m))

    unknown_msg = {"jsonrpc": "2.0", "result": "orphan"}

    call_count = [0]
    def fake_read():
        call_count[0] += 1
        if call_count[0] == 1:
            return unknown_msg
        return None

    monkeypatch.setattr(bridge, "_read_message", fake_read)
    caplog.set_level("DEBUG")
    bridge._running = True
    bridge._reader_loop()
    assert len(sent_messages) == 0
    assert "Dropping unhandled LSP message" in caplog.text


def test_reader_loop_handles_unknown_server_request(monkeypatch) -> None:
    bridge = LspJsonRpc()
    bridge._process = _fake_process()  # type: ignore[assignment]
    sent_messages: list[dict] = []
    monkeypatch.setattr(bridge, "_write_message", lambda m: sent_messages.append(m))

    server_request = {
        "jsonrpc": "2.0",
        "id": 101,
        "method": "unknown/method",
        "params": {},
    }

    call_count = [0]
    def fake_read():
        call_count[0] += 1
        if call_count[0] == 1:
            return server_request
        return None

    monkeypatch.setattr(bridge, "_read_message", fake_read)
    bridge._running = True
    bridge._reader_loop()
    assert len(sent_messages) == 1
    assert sent_messages[0]["id"] == 101
    assert sent_messages[0]["result"] is None


def test_reader_loop_still_routes_responses() -> None:
    bridge = LspJsonRpc()
    bridge._process = _fake_process()  # type: ignore[assignment]
    response_msg = {"jsonrpc": "2.0", "id": 1, "result": {"ok": True}}

    bridge._pending[1] = __import__("threading").Event()
    call_count = [0]
    def fake_read():
        call_count[0] += 1
        if call_count[0] == 1:
            return response_msg
        return None

    bridge._read_message = fake_read  # type: ignore[method-assign]
    bridge._running = True
    bridge._reader_loop()
    with bridge._lock:
        assert 1 in bridge._responses
        assert bridge._responses[1]["result"] == {"ok": True}


def test_send_request_uses_method_timeout(monkeypatch) -> None:
    bridge = LspJsonRpc()
    bridge._process = _fake_process()  # type: ignore[assignment]
    received_timeout = []

    def _fake_write(_msg):
        pass

    monkeypatch.setattr(bridge, "_write_message", _fake_write)
    monkeypatch.setattr(__import__("threading").Event, "wait", lambda self, timeout=None: (received_timeout.append(timeout), False)[-1])

    try:
        bridge.send_request("textDocument/definition", {}, id=1)
        assert False, "should have raised"
    except Exception as e:
        assert "EXT-LSP-003" in str(e)
    assert received_timeout == [3.0]


def test_send_request_sends_cancel_on_timeout(monkeypatch) -> None:
    bridge = LspJsonRpc()
    bridge._process = _fake_process()  # type: ignore[assignment]
    cancel_sent = []

    def _fake_write(msg):
        if msg.get("method") == "$/cancelRequest":
            cancel_sent.append(msg.get("params", {}).get("id"))

    monkeypatch.setattr(bridge, "_write_message", _fake_write)
    monkeypatch.setattr(__import__("threading").Event, "wait", lambda self, timeout=None: False)

    try:
        bridge.send_request("textDocument/hover", {}, id=42)
    except Exception as e:
        assert "EXT-LSP-003" in str(e)

    assert 42 in cancel_sent


def test_fail_all_pending_sets_error_responses() -> None:
    bridge = LspJsonRpc()
    bridge._pending[1] = __import__("threading").Event()
    bridge._pending[2] = __import__("threading").Event()

    bridge._fail_all_pending()

    with bridge._lock:
        assert 1 in bridge._responses
        assert 2 in bridge._responses
        assert "error" in bridge._responses[1]


def test_session_manager_rebuilds_dead_session() -> None:
    from audiagentic.components.coding_lsp.lsp_lifecycle import ServerConfig
    from audiagentic.components.coding_lsp.lsp_session_manager import SessionManager

    manager = SessionManager()
    config = ServerConfig(command=["fake-server"], file_extensions=[".py"])

    class FakeSession:
        def is_ready(self):
            return False
        def shutdown(self):
            pass

    manager._sessions["/root"] = {"python": FakeSession()}  # type: ignore[index]
    manager._last_used["/root"] = {"python": 0.0}

    call_count = [0]
    class RebuildSession:
        def initialize(self):
            call_count[0] += 1
        def initialized(self):
            pass
        def is_ready(self):
            return True
        def shutdown(self):
            pass
        server_config = config
        project_root = __import__("pathlib").Path("/root")

    original_init = None
    def fake_init(*args, **kwargs):
        return RebuildSession()

    import audiagentic.components.coding_lsp.lsp_session_manager as sm_mod
    original_cls = sm_mod.LspSession
    sm_mod.LspSession = fake_init  # type: ignore[assignment]

    try:
        session = manager.get_or_create("/root", "python", config)
        assert call_count[0] == 1
        assert session.is_ready()
    finally:
        sm_mod.LspSession = original_cls
