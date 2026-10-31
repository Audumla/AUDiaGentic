from __future__ import annotations

import socket
import subprocess
from concurrent.futures import ThreadPoolExecutor

from tests.helpers.gateway_settings import use_gateway_settings

from audiagentic.components.agents.gateway.service.bootstrap import start_or_attach_gateway
from audiagentic.components.agents.gateway.service.host import GATEWAY_SERVICE_KEY
from audiagentic.foundation.system.managed_process import (
    observe_process,
    ownership_matches,
    signal_owned_process,
)
from audiagentic.foundation.system.managed_service import ManagedServiceStore


def test_concurrent_automatic_clients_share_one_managed_gateway(monkeypatch, tmp_path):
    # Retain child diagnostics instead of losing readiness failures to DEVNULL.
    real_popen = subprocess.Popen
    startup_log = tmp_path / "startup.log"

    def logged_popen(*args, **kwargs):
        if not args or "audiagentic.components.agents.gateway.service.process" not in args[0]:
            return real_popen(*args, **kwargs)
        with startup_log.open("ab") as stream:
            kwargs.update(stdout=stream, stderr=stream)
            return real_popen(*args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", logged_popen)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    # conftest provides an isolated home with the required agents catalog;
    # replacing it here discards that startup prerequisite.
    use_gateway_settings(monkeypatch, tmp_path, port=port)
    clients = []
    store = ManagedServiceStore(GATEWAY_SERVICE_KEY)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            try:
                clients = list(pool.map(lambda _index: start_or_attach_gateway(), range(2)))
            except Exception as exc:
                raise AssertionError(startup_log.read_text(errors="replace")[-8000:]) from exc

        record = store.read()
        assert record.state == "running"
        assert record.active_lease_count == 2
        assert {client.health()["owner-epoch"] for client in clients} == {
            record.owner_epoch
        }
        assert {client.health()["lifetime-scope"] for client in clients} == {
            record.process.scope
        }
        assert {client.service_lifetime_scope for client in clients} == {
            record.process.scope
        }
        assert record.process.scope in {"shared-service-host", "session-child"}
    finally:
        for client in clients:
            client.close()
        if store.record_path.exists():
            record = store.read()
            if record.process is not None:
                observed = observe_process(record.process)
                if ownership_matches(record.process, observed):
                    signal_owned_process(record.process, observed, force=True)
