from __future__ import annotations

import socket
from concurrent.futures import ThreadPoolExecutor

from audiagentic.components.agents.gateway.service.bootstrap import start_or_attach_gateway
from audiagentic.components.agents.gateway.service.host import GATEWAY_SERVICE_KEY

from audiagentic.foundation.system.managed_process import (
    observe_process,
    ownership_matches,
    signal_owned_process,
)
from audiagentic.foundation.system.managed_service import ManagedServiceStore


def test_concurrent_automatic_clients_share_one_managed_gateway(monkeypatch, tmp_path):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    monkeypatch.setenv("AUDIAGENTIC_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("AUDIAGENTIC_GATEWAY_PORT", str(port))
    clients = []
    store = ManagedServiceStore(GATEWAY_SERVICE_KEY)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            clients = list(pool.map(lambda _index: start_or_attach_gateway(), range(2)))

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
