"""AS40: Pi RPC tee shim -- substituted at PI_ACP_PI_COMMAND.

Spawns the real `pi` process and fans its stdout to two sinks: an untouched
passthrough back to pi-acp (this process's own stdout) and a read-only raw
byte copy sent to AG's tap connection, if one is configured. stdin is passed
through to the real child byte-for-byte, untouched -- pi-acp remains the
single writer.

Byte-transparency is the load-bearing invariant: pi-acp's own stdout copy
must be indistinguishable from a direct, unshimmed exec of `pi`. The tap copy
is best-effort: any tap connect/send failure degrades AG's observation
evidence only and never touches the passthrough path (AS40
cleanup_and_recovery: "a tap failure degrades observation evidence, never
terminates or corrupts the driven session").
"""
from __future__ import annotations

import io
import os
import subprocess
import sys
import threading
from collections.abc import Callable

CHUNK_SIZE = 65536


def _read_available(source, size: int) -> bytes:
    """Read up to *size* bytes, returning as soon as any are available.

    Real OS pipes (the actual ``pi`` child's stdout/stderr, and our own
    stdin when driven by a real parent like pi-acp) are backed by a
    ``BufferedReader``, whose ``read(size)`` blocks trying to accumulate the
    *full* requested size before returning -- fine for bulk transfer, fatal
    for interactive RPC framing where a caller writes one small JSON line and
    then waits for a response: the line sits stuck in our buffer instead of
    being forwarded, and the real `pi-acp` <-> `pi` round trip never
    completes (found by running the real pi-acp + pi binaries, not the
    fake/echo children unit tests use). ``os.read`` on the raw fd has normal
    streaming semantics -- it returns whatever is currently available.  Test
    doubles (``io.BytesIO``, custom writer classes) have no real fd, so fall
    back to their own ``read()``, which is already immediate since their
    contents are fully in memory.
    """
    try:
        fd = source.fileno()
    except (AttributeError, io.UnsupportedOperation, OSError):
        return source.read(size)
    return os.read(fd, size)
TAP_ADDRESS_ENV = "AUDIAGENTIC_PI_TAP_ADDRESS"
TAP_AUTHKEY_ENV = "AUDIAGENTIC_PI_TAP_AUTHKEY"
_STDERR_CAPTURE_BOUND = 4096

# AS41 diagnostic: when the real `pi` child exits unexpectedly (EOF before
# pi-acp completes a turn), the shim's own stderr is the only place that can
# carry the child's crash reason to a human. The shim already captures a
# bounded stderr buffer internally; this env var makes it dump that buffer to
# the shim's own stderr on non-zero exit, so a test harness (or any parent
# reading the shim's stderr) can see *why* the child died instead of a silent
# EOF. Default off to preserve byte-transparency in production; the e2e
# diagnostic test sets it.
_STDERR_DUMP_ON_CRASH_ENV = "AUDIAGENTIC_PI_TAP_DUMP_STDERR_ON_CRASH"


class _TapSink:
    """Best-effort, fail-open forwarder to AG's tap connection.

    Any connect or send failure (no listener, timeout, closed pipe, wrong
    authkey) is swallowed and marks the sink permanently failed -- the tee's
    passthrough path must never depend on, or be slowed by, tap health.
    """

    def __init__(
        self,
        address: str | None,
        authkey: bytes | None,
        *,
        connect_timeout: float = 2.0,
    ) -> None:
        self._address = address
        self._authkey = authkey
        self._connect_timeout = connect_timeout
        self._connection = None
        self._failed = False

    def send(self, chunk: bytes) -> None:
        if self._failed or not self._address:
            return
        if self._connection is None:
            self._connection = self._try_connect()
            if self._connection is None:
                self._failed = True
                return
        try:
            self._connection.send_bytes(chunk)
        except OSError:
            self._failed = True
            self._close()

    def _try_connect(self):
        from audiagentic.components.providers.adapters.pi.rpc_tap_transport import connect_tap

        try:
            return connect_tap(
                self._address, authkey=self._authkey or b"", timeout=self._connect_timeout
            )
        except OSError:
            return None

    def close(self) -> None:
        self._close()

    def _close(self) -> None:
        if self._connection is not None:
            try:
                self._connection.close()
            except OSError:
                pass
            self._connection = None


def _pump_stdin(source, dest) -> None:
    """Byte-for-byte passthrough of our stdin into the child's stdin."""
    try:
        while True:
            chunk = _read_available(source, CHUNK_SIZE)
            if not chunk:
                break
            dest.write(chunk)
            dest.flush()
    except (BrokenPipeError, OSError, ValueError):
        pass
    finally:
        try:
            dest.close()
        except OSError:
            pass


def _pump_stdout(source, dest, tap: _TapSink) -> None:
    """Fan the child's stdout to (a) our own stdout unchanged, (b) the tap."""
    try:
        while True:
            chunk = _read_available(source, CHUNK_SIZE)
            if not chunk:
                break
            dest.write(chunk)
            dest.flush()
            tap.send(chunk)
    except (BrokenPipeError, OSError, ValueError):
        pass


def _drain_stderr(source, *, bound: int = _STDERR_CAPTURE_BOUND) -> bytearray:
    """Bounded stderr capture -- shim-local diagnostics only, never forwarded."""
    captured = bytearray()
    try:
        while True:
            chunk = _read_available(source, CHUNK_SIZE)
            if not chunk:
                break
            if len(captured) < bound:
                captured.extend(chunk[: bound - len(captured)])
    except (OSError, ValueError):
        pass
    return captured


def run_tee(
    argv: list[str],
    *,
    stdin,
    stdout,
    tap_address: str | None,
    tap_authkey: bytes | None,
    spawn: Callable[[list[str]], subprocess.Popen] | None = None,
    tap_connect_timeout: float = 2.0,
) -> int:
    """Spawn argv as the real Pi child and tee its stdout. Returns its exit code.

    `spawn` is injectable for tests (defaults to a real subprocess.Popen with
    piped stdio). `stdin`/`stdout` are this process's own raw byte streams
    (buffer-level, not text-wrapped) -- injectable for tests.
    """
    spawn = spawn or (
        lambda cmd: subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
    )
    child = spawn(argv)
    # Adopt the real `pi` child into a kill-on-close Job Object (Windows) so it
    # cannot outlive this shim even if the shim itself is hard-killed -- the
    # same orphan-on-crash gap `supervised_process` closes for other harness
    # grandchildren. No-op on POSIX and for test doubles without a real pid.
    _job_handle = None
    child_pid = getattr(child, "pid", None)
    if child_pid is not None:
        from audiagentic.foundation.system.supervised_process import (
            adopt_pid_into_kill_job,
        )

        _job_handle = adopt_pid_into_kill_job(child_pid)
    tap = _TapSink(tap_address, tap_authkey, connect_timeout=tap_connect_timeout)
    stderr_captured = bytearray()

    def _drain_and_capture() -> None:
        stderr_captured.extend(_drain_stderr(child.stderr))

    threads = [
        threading.Thread(target=_pump_stdin, args=(stdin, child.stdin), daemon=True),
        threading.Thread(target=_pump_stdout, args=(child.stdout, stdout, tap), daemon=True),
        threading.Thread(target=_drain_and_capture, daemon=True),
    ]
    for t in threads:
        t.start()
    exit_code = child.wait()
    for t in threads:
        t.join(timeout=2.0)
    tap.close()
    if _job_handle is not None and os.name == "nt":
        import ctypes

        try:
            ctypes.windll.kernel32.CloseHandle(_job_handle)
        except OSError:
            pass
    # AS41 diagnostic: on non-zero exit, dump the child's captured stderr to
    # our own stderr so a parent reading it can see the crash reason. Gated by
    # an env var (default off) to preserve byte-transparency in production.
    if exit_code != 0 and os.environ.get(_STDERR_DUMP_ON_CRASH_ENV) == "1" and stderr_captured:
        try:
            sys.stderr.write(
                f"\n[rpc_tap_shim] child exited code={exit_code}; "
                f"captured stderr (<= {_STDERR_CAPTURE_BOUND} bytes):\n"
            )
            sys.stderr.write(stderr_captured.decode("utf-8", errors="replace"))
            sys.stderr.write("\n[rpc_tap_shim] end captured stderr\n")
            sys.stderr.flush()
        except OSError:
            pass
    return exit_code


def main(argv: list[str] | None = None) -> int:
    argv = list(argv) if argv is not None else sys.argv[1:]
    if not argv:
        print("rpc_tap_shim: missing real pi command argv", file=sys.stderr)
        return 2
    tap_address = os.environ.get(TAP_ADDRESS_ENV) or None
    authkey_hex = os.environ.get(TAP_AUTHKEY_ENV)
    tap_authkey = bytes.fromhex(authkey_hex) if authkey_hex else None
    return run_tee(
        argv,
        stdin=sys.stdin.buffer,
        stdout=sys.stdout.buffer,
        tap_address=tap_address,
        tap_authkey=tap_authkey,
    )


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["TAP_ADDRESS_ENV", "TAP_AUTHKEY_ENV", "main", "run_tee"]