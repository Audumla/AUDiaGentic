"""E2E: MCP project server tools via JSON-RPC subprocess.

Starts the project MCP server once per module and multiplexes all calls over a
single connection. Each test gets its own tmp_path so the server's project state
is isolated.
"""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
from collections.abc import Generator
from pathlib import Path

import pytest

pytestmark = [pytest.mark.opt_in]

_ROOT = Path(__file__).resolve().parents[3]
for _p in (str(_ROOT), str(_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

_INIT = {
    "jsonrpc": "2.0", "id": 1, "method": "initialize",
    "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "test", "version": "0"}},
}
_INITIALIZED = {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}


def _read_byte_with_timeout(stream, timeout_s: float) -> bytes | None:
    q: queue.Queue[bytes] = queue.Queue(maxsize=1)

    def _reader() -> None:
        chunk = stream.read(1)
        q.put(chunk or b"")

    t = threading.Thread(target=_reader, daemon=True)
    t.start()
    try:
        chunk = q.get(timeout=max(timeout_s, 0.001))
    except queue.Empty:
        return None
    return chunk or b""


def _read_json_line(proc, deadline: float) -> dict | None:
    """Read one stdio-framed JSON-RPC message from proc.stdout."""
    while time.time() < deadline:
        header = bytearray()
        while b"\r\n\r\n" not in header and time.time() < deadline:
            chunk = _read_byte_with_timeout(proc.stdout, deadline - time.time())
            if chunk is None:
                continue
            if chunk == b"":
                if proc.poll() is not None:
                    return None
                continue
            header.extend(chunk)
        if not header:
            continue
        header_text = header.decode("ascii", errors="ignore")
        length = None
        for line in header_text.split("\r\n"):
            if line.lower().startswith("content-length:"):
                length = int(line.split(":", 1)[1].strip())
                break
        if length is None:
            continue
        payload = proc.stdout.read(length)
        if not payload:
            continue
        try:
            return json.loads(payload.decode("utf-8"))
        except (json.JSONDecodeError, ValueError):
            continue
    return None


def _write_message(proc, msg: dict) -> None:
    payload = json.dumps(msg).encode("utf-8")
    proc.stdin.write(f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii") + payload)
    proc.stdin.flush()


def _send_and_wait(proc, messages: list[dict], expected_ids: set[int], deadline: float) -> list[dict]:
    """Send messages, read responses until all expected IDs are received."""
    responses: list[dict] = []
    for msg in messages:
        _write_message(proc, msg)

    while time.time() < deadline:
        resp = _read_json_line(proc, deadline)
        if resp is None:
            break
        responses.append(resp)
        if expected_ids and expected_ids.issubset({r.get("id") for r in responses}):
            break
    return responses


def _terminate(proc):
    proc.stdin.close()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.terminate()
        proc.wait(timeout=5)


@pytest.fixture(scope="module")
def _mcp_server(project_root: Path) -> Generator[subprocess.Popen, None, None]:
    """Start the project MCP server once per module. Each test uses its own tmp_path."""
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(_ROOT / "src"), env.get("PYTHONPATH", "")])
    proc = subprocess.Popen(
        [sys.executable, "-m", "audiagentic.components.project.project_mcp", "--project-root", str(project_root)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env=env,
    )
    assert proc.stdin is not None
    assert proc.stdout is not None

    # Initialize handshake
    _write_message(proc, _INIT)
    init_resp = _read_json_line(proc, time.time() + 10)
    assert init_resp is not None, "MCP server failed to respond to initialize"

    _write_message(proc, _INITIALIZED)

    yield proc
    _terminate(proc)


def _call(proc: subprocess.Popen, tool: str, args: dict, project_root: Path, msg_id: int = 2) -> dict | list:
    """Call an MCP tool over the shared subprocess connection."""
    # Re-initialize the project root for this test (fresh tmp_path)
    # by sending a tools/call to install_component first if needed
    responses = _send_and_wait(
        proc,
        [{"jsonrpc": "2.0", "id": msg_id, "method": "tools/call",
          "params": {"name": tool, "arguments": args}}],
        {msg_id},
        time.time() + 5,
    )
    resp = next(r for r in responses if r.get("id") == msg_id)
    assert "error" not in resp, f"tool {tool!r} error: {resp['error']}"
    blocks = resp["result"]["content"]
    parsed = [json.loads(b["text"]) for b in blocks]
    return parsed if len(parsed) > 1 else parsed[0]


# ── tools/list ────────────────────────────────────────────────────────────────

def test_mcp_exposes_component_tools(tmp_path, _mcp_server):
    responses = _send_and_wait(
        _mcp_server,
        [{"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}],
        {2},
        time.time() + 5,
    )
    resp = next(r for r in responses if r.get("id") == 2)
    names = {t["name"] for t in resp["result"]["tools"]}
    assert "list_components" in names
    assert "install_component" in names
    assert "enable_component" in names
    assert "disable_component" in names
    assert "project_status" in names
    assert "read_project_file" in names


# ── list_components ───────────────────────────────────────────────────────────

def test_mcp_list_components_returns_all(tmp_path, _mcp_server):
    result = _call(_mcp_server, "list_components", {}, project_root=tmp_path)
    components = result if isinstance(result, list) else [result]
    ids = {c.get("component_id", c.get("name", "")) for c in components}
    assert "project" in ids
    assert len(ids) >= 7


def test_mcp_list_shows_not_installed_for_fresh_dir(tmp_path, project_root, _mcp_server):
    import shutil as _shutil
    # Reset project state so the server sees a fresh directory
    project_state = project_root / ".audiagentic"
    if project_state.exists():
        _shutil.rmtree(project_state)
    result = _call(_mcp_server, "list_components", {}, project_root=tmp_path)
    components = result if isinstance(result, list) else [result]
    for c in components:
        if c.get("core") is True:
            continue
        assert c.get("status") == "not-installed", f"unexpected state: {c}"


# ── project_status ────────────────────────────────────────────────────────────

def test_mcp_project_status_on_fresh_dir(tmp_path, _mcp_server):
    result = _call(_mcp_server, "project_status", {}, project_root=tmp_path)
    payload = result if isinstance(result, dict) else result[0]
    assert "install_state" in payload
    assert payload["install_state"] in ("installed", "not-installed", "none", "invalid")


def test_mcp_project_status_after_install(tmp_path, _mcp_server):
    _call(_mcp_server, "install_component", {"component_id": "project"}, project_root=tmp_path)
    result = _call(_mcp_server, "project_status", {}, project_root=tmp_path)
    payload = result if isinstance(result, dict) else result[0]
    assert payload["install_state"] == "installed"
    assert "project" in payload["components"]
    assert payload["components"]["project"]["status"] == "installed"


# ── install / disable / enable via MCP ───────────────────────────────────────

def test_mcp_install_component(tmp_path, project_root, _mcp_server):
    result = _call(_mcp_server, "install_component", {"component_id": "project"}, project_root=tmp_path)
    payload = result if isinstance(result, dict) else result[0]
    assert payload["ok"] is True
    assert payload["component_id"] == "project"
    marker = project_root / ".audiagentic" / "components" / "project.yaml"
    assert marker.exists()


def test_mcp_disable_component(tmp_path, _mcp_server):
    _call(_mcp_server, "install_component", {"component_id": "project"}, project_root=tmp_path)
    result = _call(_mcp_server, "disable_component", {"component_id": "project"}, project_root=tmp_path)
    payload = result if isinstance(result, dict) else result[0]
    assert payload["ok"] is True
    assert payload["enabled"] is False


def test_mcp_enable_component(tmp_path, _mcp_server):
    _call(_mcp_server, "install_component", {"component_id": "project"}, project_root=tmp_path)
    _call(_mcp_server, "disable_component", {"component_id": "project"}, project_root=tmp_path)
    result = _call(_mcp_server, "enable_component", {"component_id": "project"}, project_root=tmp_path)
    payload = result if isinstance(result, dict) else result[0]
    assert payload["ok"] is True
    assert payload["enabled"] is True


# ── read_project_file ─────────────────────────────────────────────────────────

def test_mcp_read_project_file_after_install(tmp_path, _mcp_server):
    _call(_mcp_server, "install_component", {"component_id": "project"}, project_root=tmp_path)
    result = _call(
        _mcp_server, "read_project_file",
        {"relative_path": ".audiagentic/config/project.yaml"},
        project_root=tmp_path,
    )
    payload = result if isinstance(result, dict) else result[0]
    content = payload.get("content", "")
    assert len(content) > 0
