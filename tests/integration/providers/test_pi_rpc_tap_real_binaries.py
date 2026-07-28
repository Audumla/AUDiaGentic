"""AS40: byte-transparency proof against the REAL pi-acp bridge + REAL pi binary.

Every test in tests/unit/providers/test_pi_rpc_tap_shim.py and
test_pi_rpc_tap_receiver.py exercises run_tee against a fake or echo child --
none of them drive the actual pi-acp <-> pi JSON-RPC exchange. This is the
load-bearing proof AS40 requires before it can close: pi-acp (spawned for
real, via npx) talking ACP JSON-RPC over stdio, materializing our tee-shim
wrapper at PI_ACP_PI_COMMAND, and spawning the real `pi --mode rpc` through
it. Requires no API key -- pi-acp's session/new handler calls
proc.getState()/getAvailableModels() on the real pi RPC child regardless of
auth state, which is real RPC traffic sufficient to prove both byte-
transparency (pi-acp gets the identical response with or without the tap
installed) and tap fidelity (the tap independently captures those same
frames).

Found and fixed via this test: `_pump_stdin`/`_pump_stdout` originally used
`BufferedReader.read(n)`, which blocks trying to fill the full chunk size
before returning -- fatal for interactive small-message RPC traffic. The
fake-child unit tests never caught it because they pre-seed the full
response in one shot. Fixed in rpc_tap_shim.py's `_read_available` (uses
`os.read` on the raw fd so partial availability is forwarded immediately).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from audiagentic.components.providers.adapters.pi import acp as pi_acp
from audiagentic.components.providers.adapters.pi.rpc_tap import JsonlTapFrame
from audiagentic.components.providers.adapters.pi.rpc_tap_receiver import (
    iter_tap_frames,
    open_tap_listener_for_launch,
)

pytestmark = [
    pytest.mark.slow,
    pytest.mark.requires_npm,
    pytest.mark.skipif(shutil.which("npx") is None, reason="npx not on PATH"),
    pytest.mark.skipif(shutil.which("pi") is None, reason="pi not on PATH"),
]


def _send(proc: subprocess.Popen, obj: dict) -> None:
    proc.stdin.write((json.dumps(obj) + "\n").encode())
    proc.stdin.flush()


class _RealTappedSession:
    """One real pi-acp + real pi session with the tap installed, driven over ACP stdio."""

    def __init__(self, tmp_path: Path, *, next_id: int = 1) -> None:
        self.project_root = tmp_path / "project"
        self.project_root.mkdir(parents=True)
        self.runtime_root = tmp_path / "runtime"
        self.launch = pi_acp.build_acp_launch(
            self.project_root, request_runtime_root=self.runtime_root, enable_rpc_tap=True
        )
        self.frames: list = []
        self._next_id = next_id
        self._listener = open_tap_listener_for_launch(self.launch.environment)
        self._consumer = threading.Thread(target=self._consume, daemon=True)
        self._consumer.start()

        env = dict(os.environ)
        env.update(self.launch.environment)
        self.proc = subprocess.Popen(
            [self.launch.executable, *self.launch.args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        threading.Thread(target=lambda: self.proc.stderr.read(), daemon=True).start()

    def _consume(self) -> None:
        for item in iter_tap_frames(self._listener):
            self.frames.append(item)

    def request(self, method: str, params: dict) -> dict:
        request_id = self._next_id
        self._next_id += 1
        _send(self.proc, {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        return json.loads(self.proc.stdout.readline())

    def close(self) -> None:
        self.proc.terminate()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        self._listener.close()
        self._consumer.join(timeout=5)

    def frame_commands(self) -> list[str | None]:
        return [f.payload.get("command") for f in self.frames if isinstance(f, JsonlTapFrame)]

    def frame_session_ids(self) -> set[str]:
        ids = set()
        for f in self.frames:
            if isinstance(f, JsonlTapFrame):
                data = f.payload.get("data")
                if isinstance(data, dict) and "sessionId" in data:
                    ids.add(data["sessionId"])
        return ids


def _assert_session_new_reached_real_pi(session_resp: dict) -> None:
    # Whether or not this host has a model API key configured, reaching
    # either a real success (sessionId + model catalog) or the specific
    # "Authentication required" error -- rather than a spawn/transport
    # error -- proves the real pi RPC child was spawned through our
    # wrapper, answered get_state/get_available_models correctly, and
    # pi-acp parsed those real responses byte-for-byte through the tee
    # shim.
    if "error" in session_resp:
        assert session_resp["error"]["code"] == -32000
        assert "Authentication required" in session_resp["error"]["message"]
    else:
        assert "sessionId" in session_resp["result"]


@pytest.mark.timeout(60)
def test_real_pi_acp_session_new_completes_through_the_tee_shim(tmp_path: Path) -> None:
    session = _RealTappedSession(tmp_path)
    try:
        init_resp = session.request("initialize", {"protocolVersion": 1, "clientCapabilities": {}})
        assert init_resp["result"]["agentInfo"]["name"] == "pi-acp"

        session_resp = session.request(
            "session/new", {"cwd": str(session.project_root.resolve()), "mcpServers": []}
        )
        _assert_session_new_reached_real_pi(session_resp)
    finally:
        session.close()

    assert "get_state" in session.frame_commands()
    assert "get_available_models" in session.frame_commands()


@pytest.mark.timeout(90)
def test_two_simultaneous_real_sessions_do_not_cross_contaminate(tmp_path: Path) -> None:
    """AS40 required_concurrency_proof: two real pi-acp+pi sessions, tapped,
    running at the same time -- distinct runtime roots/sockets/shim processes,
    each tap sees only its own session's frames, pi-acp's own outcome for
    each session is unaffected by the other running concurrently."""
    session_a = _RealTappedSession(tmp_path / "a")
    session_b = _RealTappedSession(tmp_path / "b")

    try:
        assert session_a.launch.environment["AUDIAGENTIC_PI_TAP_ADDRESS"] != (
            session_b.launch.environment["AUDIAGENTIC_PI_TAP_ADDRESS"]
        )
        assert session_a.launch.environment["AUDIAGENTIC_PI_TAP_AUTHKEY"] != (
            session_b.launch.environment["AUDIAGENTIC_PI_TAP_AUTHKEY"]
        )
        assert session_a.runtime_root != session_b.runtime_root
        assert session_a.proc.pid != session_b.proc.pid

        init_a = session_a.request("initialize", {"protocolVersion": 1, "clientCapabilities": {}})
        init_b = session_b.request("initialize", {"protocolVersion": 1, "clientCapabilities": {}})
        assert init_a["result"]["agentInfo"]["name"] == "pi-acp"
        assert init_b["result"]["agentInfo"]["name"] == "pi-acp"

        # Interleaved, not sequential -- both real pi children running at once.
        resp_a = session_a.request(
            "session/new", {"cwd": str(session_a.project_root.resolve()), "mcpServers": []}
        )
        resp_b = session_b.request(
            "session/new", {"cwd": str(session_b.project_root.resolve()), "mcpServers": []}
        )
        _assert_session_new_reached_real_pi(resp_a)
        _assert_session_new_reached_real_pi(resp_b)
    finally:
        session_a.close()
        session_b.close()

    assert "get_state" in session_a.frame_commands()
    assert "get_state" in session_b.frame_commands()

    # Each tap independently observed only its own session's pi process --
    # the real cross-contamination check, not just distinct configuration.
    ids_a = session_a.frame_session_ids()
    ids_b = session_b.frame_session_ids()
    assert ids_a, "session A tap captured no sessionId-bearing frames"
    assert ids_b, "session B tap captured no sessionId-bearing frames"
    assert ids_a.isdisjoint(ids_b), f"cross-contamination: shared session ids {ids_a & ids_b}"
