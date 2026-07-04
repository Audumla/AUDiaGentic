"""E2E: component MCP servers via JSON-RPC subprocess.

Starts one subprocess per MCP server module per module and multiplexes all calls
over that shared connection. Each test gets its own tmp_path so project state is
isolated.
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
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-03-26",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "0"},
    },
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


def _read_json_line(proc: subprocess.Popen, deadline: float) -> dict | None:
    assert proc.stdout is not None
    while time.time() < deadline:
        header = bytearray()
        while b"\r\n\r\n" not in header and b"\n" not in header and time.time() < deadline:
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
        if b"\r\n\r\n" not in header:
            try:
                return json.loads(bytes(header).decode("utf-8"))
            except (json.JSONDecodeError, ValueError):
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


def _write_message(proc: subprocess.Popen, msg: dict) -> None:
    assert proc.stdin is not None
    proc.stdin.write((json.dumps(msg) + "\n").encode("utf-8"))
    proc.stdin.flush()


def _send_and_wait(
    proc: subprocess.Popen,
    messages: list[dict],
    expected_ids: set[int],
    deadline: float,
) -> list[dict]:
    assert proc.stdin is not None
    for msg in messages:
        _write_message(proc, msg)

    responses: list[dict] = []
    while time.time() < deadline:
        resp = _read_json_line(proc, deadline)
        if resp is None:
            break
        responses.append(resp)
        if expected_ids and expected_ids.issubset({r.get("id") for r in responses}):
            break
    return responses


def _terminate(proc: subprocess.Popen) -> None:
    assert proc.stdin is not None
    proc.stdin.close()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.terminate()
        proc.wait(timeout=5)


def _server_fixture(module: str, extra_args: list[str] | None = None):
    """Create a module-scoped fixture for a given MCP server module."""

    @pytest.fixture(scope="module")
    def _fixture(project_root: Path) -> Generator[subprocess.Popen, None, None]:
        env = dict(os.environ)
        env["AUDIAGENTIC_REPO_ROOT"] = str(project_root)
        env["PYTHONPATH"] = os.pathsep.join([str(_ROOT / "src"), env.get("PYTHONPATH", "")])
        command = [sys.executable, "-m", module]
        if extra_args:
            command.extend(extra_args)
        proc = subprocess.Popen(
            command,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=env,
        )
        assert proc.stdin is not None
        assert proc.stdout is not None

        _write_message(proc, _INIT)
        init_resp = _read_json_line(proc, time.time() + 10)
        assert init_resp is not None, f"MCP server {module} failed to respond to initialize"

        _write_message(proc, _INITIALIZED)

        yield proc
        _terminate(proc)

    return _fixture


# ── Shared server fixtures (one per module) ──────────────────────────────────

_session_server = _server_fixture("audiagentic.components.session.session_mcp", ["--readonly", "--smoke-only"])
_project_server = _server_fixture("audiagentic.components.project.project_mcp")
_providers_server = _server_fixture("audiagentic.components.providers.providers_mcp")
_release_server = _server_fixture("audiagentic.components.release.release_please.release_please_mcp")


def _call(
    proc: subprocess.Popen,
    tool: str,
    args: dict,
    project_root: Path,
    msg_id: int = 2,
) -> dict | list:
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


def _tools_list(proc: subprocess.Popen, project_root: Path, msg_id: int = 2) -> set[str]:
    responses = _send_and_wait(
        proc,
        [{"jsonrpc": "2.0", "id": msg_id, "method": "tools/list", "params": {}}],
        {msg_id},
        time.time() + 5,
    )
    resp = next(r for r in responses if r.get("id") == msg_id)
    return {tool["name"] for tool in resp["result"]["tools"]}


# ── session server tests ─────────────────────────────────────────────────────

def test_session_server_exposes_expected_tools(tmp_path, _session_server):
    names = _tools_list(_session_server, tmp_path)
    assert {
        "status", "config", "set_auto_update", "cli_visibility",
        "set_cli_visibility", "update_rig",
    }.issubset(names)


def test_session_server_status_returns_environment(tmp_path, project_root, _session_server):
    result = _call(_session_server, "status", {}, project_root=tmp_path)
    payload = result if isinstance(result, dict) else result[0]
    assert payload["environment"]["repo_root"] == str(project_root)
    assert "versions" in payload


@pytest.mark.opt_in
def test_session_server_update_rig(tmp_path, _session_server):
    result = _send_and_wait(
        _session_server,
        [{"jsonrpc": "2.0", "id": 2, "method": "tools/call",
          "params": {"name": "update_rig", "arguments": {"scope": "local"},
                     "_meta": {"progressToken": "test-2"}}}],
        {2},
        time.time() + 60,
    )
    resp = next(r for r in result if r.get("id") == 2)
    assert "error" not in resp, f"update_rig error: {resp['error']}"
    blocks = resp["result"]["content"]
    parsed = [json.loads(b["text"]) for b in blocks]
    payload = parsed[0] if len(parsed) == 1 else parsed[0] if isinstance(parsed[0], dict) else parsed
    assert isinstance(payload, dict)
    assert payload["ok"] is True
    assert "output" in payload


def test_session_server_detects_active_embedded_rig_profile(monkeypatch) -> None:
    from audiagentic.components.session.session_embedded_rig import (
        active_embedded_rig_profile,
    )
    monkeypatch.setenv("AUDIAGENTIC_RIG_TYPE", "embedded")
    monkeypatch.setenv("AUDIAGENTIC_RIG_PROFILE", "qwen3.5-2b-q4_k_s")
    assert active_embedded_rig_profile() == "qwen3.5-2b-q4_k_s"


# ── project server tests ─────────────────────────────────────────────────────

def test_project_server_exposes_expected_tools(tmp_path, _project_server):
    names = _tools_list(_project_server, tmp_path)
    assert {
        "project_status", "list_components", "install_component",
        "uninstall_component", "enable_component", "disable_component",
    }.issubset(names)


def test_project_server_lists_optional_components_not_installed(tmp_path, _project_server):
    result = _call(_project_server, "list_components", {}, project_root=tmp_path)
    payload = result if isinstance(result, list) else [result]
    components = {c["component_id"]: c for c in payload}
    assert "providers" in components
    assert components["providers"]["status"] == "not-installed"
    assert components["providers"]["enabled"] is None


# ── providers server tests ───────────────────────────────────────────────────

def test_providers_server_exposes_expected_tools(tmp_path, _providers_server):
    names = _tools_list(_providers_server, tmp_path)
    assert {
        "list_providers", "get_provider_status",
        "list_provider_descriptors", "reconcile_all_providers",
    }.issubset(names)


def test_providers_server_lists_known_providers(tmp_path, _providers_server):
    result = _call(_providers_server, "list_providers", {}, project_root=tmp_path)
    payload = result if isinstance(result, dict) else result[0]
    provider_ids = {p["provider_id"] for p in payload["providers"]}
    assert "codex" in provider_ids
    assert "gemini" in provider_ids


# ── release-please server tests ──────────────────────────────────────────────

def test_release_please_server_exposes_expected_tools(tmp_path, _release_server):
    names = _tools_list(_release_server, tmp_path)
    assert {"install_release_please", "update_release_please_workflow"}.issubset(names)


# ── direct unit-style test (no subprocess) ───────────────────────────────────

def test_update_rig_works_directly(tmp_path: Path) -> None:
    """Test the update_binaries work function directly (avoids MCP subprocess timeout)."""
    import contextlib
    import io

    from audiagentic.foundation.contracts.output import ComponentOutputEvent
    from audiagentic.foundation.home import global_harness_runtime
    from audiagentic.runtime.rig.embedded.binaries import update_binaries as _update

    os.environ["AUDIAGENTIC_HOME"] = str(tmp_path / ".audiagentic")
    out = io.StringIO()
    events = []

    def _sink(event: ComponentOutputEvent) -> None:
        events.append(event)

    harness = global_harness_runtime()
    with contextlib.redirect_stdout(out):
        _update(runtime_dir=harness)
    _sink(ComponentOutputEvent(message=out.getvalue().strip()))

    assert len(events) > 0
    assert "llama-server" in events[-1].message or "Installed" in events[-1].message or "up to date" in events[-1].message
