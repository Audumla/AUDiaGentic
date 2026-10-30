"""A gateway port held by something else is explained, with the setting that fixes it."""
from __future__ import annotations

import socket
from pathlib import Path
from types import SimpleNamespace

from audiagentic.components.agents.configuration import doctor_checks
from audiagentic.components.agents.gateway.service import port_holder
from audiagentic.foundation.lifecycle.doctor import OK, WARN


class _Store:
    def __init__(self, running: bool) -> None:
        self._running = running

    def read(self):
        if not self._running:
            raise FileNotFoundError
        return SimpleNamespace(state="running", process=SimpleNamespace(pid=1))


def _check(*, running=False, in_use=True, holder=None, home="/homes/mine"):
    return port_holder.check_gateway_port(port=8765, home=Path(home), store=_Store(running),
                                          in_use=lambda _p: in_use, holder_of=lambda _p: holder)


def test_own_running_service_or_a_free_port_is_fine() -> None:
    assert _check(running=True).status == "ok"
    assert _check(in_use=False).status == "ok"


def test_port_held_by_another_homes_service_names_that_home() -> None:
    finding = _check(holder=port_holder.Holder(77, "python -m gateway", "/homes/other"))
    assert finding.status == "held-by-other" and "/homes/other" in finding.detail and "77" in finding.detail


def test_port_held_by_a_process_of_this_home_without_a_record_is_still_reported() -> None:
    finding = _check(holder=port_holder.Holder(77, "python -m gateway", "/homes/mine"))
    assert finding.status == "held-by-other" and "no gateway service record" in finding.detail


def test_unidentifiable_holder_is_unknown_not_blamed() -> None:
    assert _check(holder=None).status == "unknown"


def test_real_probe_sees_a_listening_socket_and_finds_it_in_proc() -> None:
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]
        assert port_holder.port_in_use(port)
        if Path("/proc/net/tcp").exists():
            holder = port_holder.find_holder(port)
            assert holder is not None and holder.pid is not None
    assert not port_holder.port_in_use(port)


def test_doctor_check_gives_a_fix_that_names_the_home_setting(monkeypatch) -> None:
    other = port_holder.PortFinding("held-by-other", "port held", 8765, port_holder.Holder(7, "g", "/homes/other"))
    monkeypatch.setattr(port_holder, "check_gateway_port", lambda: other)
    [result] = doctor_checks.check_gateway_port(SimpleNamespace())
    assert result.status == WARN and "home: /homes/other" in result.fix and "gateway.port" in result.fix
    monkeypatch.setattr(port_holder, "check_gateway_port", lambda: port_holder.PortFinding("ok", "free", 8765))
    assert doctor_checks.check_gateway_port(SimpleNamespace())[0].status == OK
