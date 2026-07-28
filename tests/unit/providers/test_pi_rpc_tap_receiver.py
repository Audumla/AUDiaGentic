"""AS40 step 3: end-to-end receiver test wiring acp.py's tap config through
rpc_tap_transport -> rpc_tap_shim -> rpc_tap_receiver -> rpc_tap codec.

Does not invoke the real pi-acp bridge or the real `pi` binary (those require
the installed npm packages, exercised separately by the byte-transparency
proof still pending on AS40) -- run_tee's real-subprocess mode is used with a
small inline "fake pi" script that emits JSONL lines, proving the full chain
from a launch's tap configuration through to decoded frames at the receiver.
"""
from __future__ import annotations

import io
import json
import subprocess
import sys
import threading

from audiagentic.components.providers.adapters.pi import acp as pi_acp
from audiagentic.components.providers.adapters.pi.rpc_tap import JsonlTapFrame
from audiagentic.components.providers.adapters.pi.rpc_tap_receiver import (
    iter_tap_frames,
    open_tap_listener_for_launch,
    tap_listener_config,
)
from audiagentic.components.providers.adapters.pi.rpc_tap_shim import run_tee


class _CapturingWriter(io.RawIOBase):
    def __init__(self) -> None:
        self.captured = bytearray()

    def write(self, chunk: bytes) -> int:
        self.captured.extend(chunk)
        return len(chunk)

    def flush(self) -> None:
        pass

    def close(self) -> None:  # keep captured data readable after "close"
        pass


def test_tap_listener_config_is_none_without_a_tap() -> None:
    assert tap_listener_config({}) is None


def test_full_chain_from_launch_config_to_decoded_frames(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(pi_acp, "_system_pi_acp_argv", lambda: ["pi-acp"])
    monkeypatch.setattr(pi_acp.shutil, "which", lambda name: "pi" if name == "pi" else None)

    launch = pi_acp.build_acp_launch(
        tmp_path, request_runtime_root=tmp_path / "runtime", enable_rpc_tap=True
    )

    listener = open_tap_listener_for_launch(launch.environment)
    frames: list = []

    def _consume() -> None:
        for item in iter_tap_frames(listener):
            frames.append(item)

    consumer = threading.Thread(target=_consume, daemon=True)
    consumer.start()

    fake_pi_script = (
        "import sys, json\n"
        "for obj in [{'type': 'agent_start'}, {'type': 'agent_end'}]:\n"
        "    sys.stdout.buffer.write((json.dumps(obj) + chr(10)).encode())\n"
        "    sys.stdout.buffer.flush()\n"
    )
    writer = _CapturingWriter()

    code = run_tee(
        [sys.executable, "-c", fake_pi_script],
        stdin=io.BytesIO(b""),
        stdout=writer,
        tap_address=launch.environment["AUDIAGENTIC_PI_TAP_ADDRESS"],
        tap_authkey=bytes.fromhex(launch.environment["AUDIAGENTIC_PI_TAP_AUTHKEY"]),
        spawn=lambda cmd: subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        ),
    )
    assert code == 0

    consumer.join(timeout=5.0)
    listener.close()

    decoded_types = [f.payload["type"] for f in frames if isinstance(f, JsonlTapFrame)]
    assert decoded_types == ["agent_start", "agent_end"]

    passthrough = bytes(writer.captured).decode("utf-8")
    assert json.loads(passthrough.splitlines()[0])["type"] == "agent_start"
