"""SH63: a restart's replacement waits for the retiring owner to release the port instead of failing."""
from __future__ import annotations

import errno
import socket
import threading
import time
from types import SimpleNamespace

import pytest

from audiagentic.components.agents.gateway.service import host as host_module
from audiagentic.components.agents.gateway.service import process


def _in_use() -> OSError:
    return OSError(errno.EADDRINUSE, "Address already in use")


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def test_a_held_port_is_retried_until_it_is_released() -> None:
    clock, attempts = _Clock(), []

    def make():
        attempts.append(clock.now)
        if len(attempts) < 4:
            raise _in_use()
        return "server"

    assert host_module.bind_with_wait(make, 5.0, sleep=clock.sleep, clock=clock) == "server" and len(attempts) == 4


def test_the_wait_is_bounded_and_the_original_error_is_raised() -> None:
    clock = _Clock()
    calls = []

    def make():
        calls.append(1)
        raise _in_use()

    with pytest.raises(OSError) as raised:
        host_module.bind_with_wait(make, 1.0, sleep=clock.sleep, clock=clock)
    assert raised.value.errno == errno.EADDRINUSE and 4 <= len(calls) <= 7 and clock.now >= 1.0


def test_without_a_wait_a_held_port_fails_at_once_and_other_errors_are_never_retried() -> None:
    calls = []

    def held():
        calls.append(1)
        raise _in_use()

    with pytest.raises(OSError):
        host_module.bind_with_wait(held, 0.0)
    assert calls == [1]

    def denied():
        calls.append(2)
        raise PermissionError(errno.EACCES, "denied")

    with pytest.raises(PermissionError):
        host_module.bind_with_wait(denied, 30.0)
    assert calls == [1, 2]


def test_a_real_held_port_is_taken_over_once_the_holder_lets_go() -> None:
    holder = socket.socket()
    holder.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
    holder.bind(("127.0.0.1", 0))
    holder.listen(1)
    port = holder.getsockname()[1]
    threading.Timer(0.5, holder.close).start()

    def bind():
        sock = socket.socket()
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            sock.close()
            raise
        return sock

    started = time.monotonic()
    taken = host_module.bind_with_wait(bind, 10.0)
    taken.close()
    assert 0.3 <= time.monotonic() - started < 8.0


def test_the_replacement_gets_a_bind_wait_exactly_once(monkeypatch) -> None:
    launched = []
    monkeypatch.setattr(process.subprocess, "Popen", lambda args, **kwargs: launched.append(args))
    process._launch_replacement(["--port", "8765", "--token-file", "t"])
    process._launch_replacement(["--port", "8765", "--bind-wait", "5"])
    assert launched[0][-2:] == ["--bind-wait", str(process._REPLACEMENT_BIND_WAIT_SECONDS)]
    assert launched[1].count("--bind-wait") == 1 and launched[1][-1] == "5"


def test_the_service_passes_the_wait_to_its_host_and_a_first_start_has_none(monkeypatch) -> None:
    seen = []
    host = SimpleNamespace(lifecycle=SimpleNamespace(restart_requested=False, exit_reason="stop"), serve_forever=lambda: None,
                           close=lambda: None)
    monkeypatch.setattr(process.GatewayServiceHost, "create", lambda **kwargs: seen.append(kwargs) or host)
    process.main(["--port", "8765", "--token-file", "token"])
    process.main(["--port", "8765", "--token-file", "token", "--bind-wait", "12.5"])
    assert seen[0]["bind_wait"] == 0.0 and seen[1]["bind_wait"] == 12.5


def test_the_listening_socket_is_closed_before_the_replacement_is_launched(monkeypatch) -> None:
    events = []
    server = SimpleNamespace(server_close=lambda: events.append("port released"))
    host = SimpleNamespace(lifecycle=SimpleNamespace(restart_requested=True), serve_forever=lambda: None,
                           close=lambda: events.append("closed"), server=server)
    monkeypatch.setattr(process.GatewayServiceHost, "create", lambda **kwargs: host)
    monkeypatch.setattr(process.subprocess, "Popen", lambda args, **kwargs: events.append("launched"))
    monkeypatch.setattr(process.os, "_exit", lambda code: events.append("exit"))
    process.main(["--port", "8765", "--token-file", "token"])
    assert events == ["closed", "port released", "launched", "exit"]


def test_a_failing_socket_close_never_blocks_the_handoff() -> None:
    def broken():
        raise RuntimeError("already closed")

    process._release_port(SimpleNamespace(server=SimpleNamespace(server_close=broken)))
    process._release_port(SimpleNamespace())  # no server attribute at all
