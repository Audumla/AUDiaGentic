"""AS40 step 2: tee-core and transport tests for the Pi RPC tap shim.

run_tee() is transport-agnostic and takes an injectable `spawn` + raw
stdin/stdout streams, so the passthrough/byte-transparency logic is fully
unit-testable without a real `pi` binary. The transport tests exercise the
real platform IPC (AF_UNIX on POSIX, AF_PIPE on Windows) via
rpc_tap_transport, in-process. Not covered here (still pending on AS40): a
real pi-acp + real pi byte-transparency proof, concurrent two-session
non-contamination, and full crash/restart cleanup matrices.
"""
from __future__ import annotations

import io
import subprocess
import sys
import threading
import uuid
from pathlib import Path

from audiagentic.components.providers.adapters.pi import rpc_tap_transport
from audiagentic.components.providers.adapters.pi.rpc_tap_shim import run_tee


class _CapturingWriter(io.RawIOBase):
    """Sink that records every write and survives close() (tests inspect after)."""

    def __init__(self) -> None:
        self.captured = bytearray()
        self._closed_calls = 0

    def write(self, chunk: bytes) -> int:
        self.captured.extend(chunk)
        return len(chunk)

    def flush(self) -> None:
        pass

    def close(self) -> None:  # keep captured data readable after "close"
        self._closed_calls += 1


class _FakeChild:
    """Stand-in for subprocess.Popen with pre-seeded stdout/stderr."""

    def __init__(self, stdout_bytes: bytes = b"", stderr_bytes: bytes = b"", exit_code: int = 0) -> None:
        self.stdin = _CapturingWriter()
        self.stdout = io.BytesIO(stdout_bytes)
        self.stderr = io.BytesIO(stderr_bytes)
        self._exit_code = exit_code

    def wait(self) -> int:
        return self._exit_code


def test_stdin_passthrough_is_byte_for_byte() -> None:
    child = _FakeChild(stdout_bytes=b"")
    sent = b"prompt command bytes\n"
    code = run_tee(
        ["fake"],
        stdin=io.BytesIO(sent),
        stdout=_CapturingWriter(),
        tap_address=None,
        tap_authkey=None,
        spawn=lambda argv: child,
    )
    assert code == 0
    assert bytes(child.stdin.captured) == sent


def test_stdout_passthrough_is_byte_for_byte() -> None:
    produced = b'{"type":"agent_start"}\n{"type":"agent_end"}\n'
    child = _FakeChild(stdout_bytes=produced)
    our_stdout = _CapturingWriter()
    code = run_tee(
        ["fake"],
        stdin=io.BytesIO(b""),
        stdout=our_stdout,
        tap_address=None,
        tap_authkey=None,
        spawn=lambda argv: child,
    )
    assert code == 0
    assert bytes(our_stdout.captured) == produced


def test_exit_code_is_forwarded_unchanged() -> None:
    child = _FakeChild(exit_code=17)
    code = run_tee(
        ["fake"],
        stdin=io.BytesIO(b""),
        stdout=_CapturingWriter(),
        tap_address=None,
        tap_authkey=None,
        spawn=lambda argv: child,
    )
    assert code == 17


def test_no_tap_address_means_no_tap_attempted_and_passthrough_still_works() -> None:
    produced = b"just pi output\n"
    child = _FakeChild(stdout_bytes=produced)
    our_stdout = _CapturingWriter()
    code = run_tee(
        ["fake"],
        stdin=io.BytesIO(b""),
        stdout=our_stdout,
        tap_address=None,
        tap_authkey=None,
        spawn=lambda argv: child,
    )
    assert code == 0
    assert bytes(our_stdout.captured) == produced


def test_unreachable_tap_fails_open_passthrough_unaffected(tmp_path: Path) -> None:
    """A tap that can never connect must not change stdout fidelity or block."""
    produced = b'{"type":"agent_settled"}\n'
    child = _FakeChild(stdout_bytes=produced)
    our_stdout = _CapturingWriter()
    dead_address = rpc_tap_transport.tap_address(tmp_path / "no-listener-here")
    code = run_tee(
        ["fake"],
        stdin=io.BytesIO(b""),
        stdout=our_stdout,
        tap_address=dead_address,
        tap_authkey=b"unused",
        spawn=lambda argv: child,
        tap_connect_timeout=0.1,
    )
    assert code == 0
    assert bytes(our_stdout.captured) == produced


def test_tap_receives_the_same_bytes_as_the_passthrough_copy(tmp_path: Path) -> None:
    """The AG-bound tap copy must match the pi-acp-bound copy exactly."""
    produced = b'{"type":"agent_start"}\n{"type":"message_update"}\n{"type":"agent_end"}\n'
    child = _FakeChild(stdout_bytes=produced)
    our_stdout = _CapturingWriter()
    address = rpc_tap_transport.tap_address(tmp_path)
    authkey = uuid.uuid4().bytes

    received: list[bytes] = []

    def _accept_once() -> None:
        listener = rpc_tap_transport.open_tap_listener(address, authkey=authkey)
        try:
            conn = listener.accept()
            try:
                while True:
                    received.append(conn.recv_bytes())
            except EOFError:
                pass
            finally:
                conn.close()
        finally:
            listener.close()

    server_thread = threading.Thread(target=_accept_once, daemon=True)
    server_thread.start()

    code = run_tee(
        ["fake"],
        stdin=io.BytesIO(b""),
        stdout=our_stdout,
        tap_address=address,
        tap_authkey=authkey,
        spawn=lambda argv: child,
    )
    server_thread.join(timeout=5.0)

    assert code == 0
    assert bytes(our_stdout.captured) == produced
    assert b"".join(received) == produced


def test_real_subprocess_echo_through_the_full_tee() -> None:
    """End-to-end with a real child process (not the real `pi` binary, but a
    real OS subprocess) -- proves the threading/pipe wiring works against
    genuine subprocess stdio, not just BytesIO fakes."""
    echo_script = "import sys; data = sys.stdin.buffer.read(); sys.stdout.buffer.write(data)"
    argv = [sys.executable, "-c", echo_script]
    sent = b"line one\nline two\n"
    our_stdout = _CapturingWriter()
    code = run_tee(
        argv,
        stdin=io.BytesIO(sent),
        stdout=our_stdout,
        tap_address=None,
        tap_authkey=None,
        spawn=lambda cmd: subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        ),
    )
    assert code == 0
    assert bytes(our_stdout.captured) == sent


def test_tap_address_is_stable_for_the_same_runtime_root(tmp_path: Path) -> None:
    assert rpc_tap_transport.tap_address(tmp_path) == rpc_tap_transport.tap_address(tmp_path)


def test_tap_address_differs_for_different_runtime_roots(tmp_path: Path) -> None:
    other = tmp_path / "other"
    other.mkdir()
    assert rpc_tap_transport.tap_address(tmp_path) != rpc_tap_transport.tap_address(other)
