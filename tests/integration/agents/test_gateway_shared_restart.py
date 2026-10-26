"""Real shared HTTPS verifies cached clients across a durable owner epoch change."""
from __future__ import annotations

import ssl
import threading
from unittest.mock import Mock

import pytest
from tests.integration.agents.test_gateway_shared_https import _certificate

from audiagentic.components.agents.gateway.remote_client import StandaloneGatewayClient
from audiagentic.components.agents.gateway.service.application import GatewayServiceApplication
from audiagentic.components.agents.gateway.service.contract import PROTOCOL_VERSION
from audiagentic.components.agents.gateway.service.http_transport import GatewayHTTPServer
from audiagentic.components.agents.gateway.service.shared_config import (
    SharedGatewayPrincipal,
    SharedGatewayServerConfig,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.system.managed_service import ManagedServiceStore
from audiagentic.foundation.system.managed_service_contracts import ServiceKey


class Application:
    def __init__(self):
        self.cancels = 0
        self.reads = 0

    def get_execution_request(self, root, request_id, **kwargs):
        self.reads += 1
        return {"request_id": request_id, "lifecycle": "active", "activity_seq": 0}

    def cancel_execution_request(self, root, request_id):
        self.cancels += 1
        return {"request-id": request_id, "state": "cancelled"}


@pytest.fixture
def service(tmp_path):
    cert, key = _certificate(tmp_path)
    principals = []
    for name in ("alice", "bob"):
        token = tmp_path / f"{name}.token"
        token.write_text(f"token-{name}")
        principals.append(SharedGatewayPrincipal(name, token, frozenset({"one"}), frozenset({"read", "cancel"})))
    config = SharedGatewayServerConfig(server_id="restart", port=0, service_root=tmp_path / "service", projects={"one": tmp_path}, principals=tuple(principals))
    store = ManagedServiceStore(ServiceKey("gateway", "restart-http"), root=config.service_root)
    record = store.create(protocol_version=PROTOCOL_VERSION, owner_epoch="epoch-one")
    store.transition("running", expected_revision=record.revision, expected_epoch=record.owner_epoch)
    domain = Application()
    owner = GatewayServiceApplication(domain, store)
    server = GatewayHTTPServer(("127.0.0.1", 0), owner, "local-only", shared_config=config)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    clients = []

    def client(name="alice"):
        result = StandaloneGatewayClient(f"https://127.0.0.1:{server.server_port}", f"token-{name}", shared_server_id="restart", shared_project_id="one", ssl_context=ssl.create_default_context(cafile=str(cert)), request_timeout=3)
        result.connect()
        clients.append(result)
        return result

    def rotate():
        for state in ("stopping", "stopped", "starting", "running"):
            record = store.read()
            extra = {"new_owner_epoch": "epoch-two"} if state == "starting" else {}
            store.transition(state, expected_revision=record.revision, expected_epoch=record.owner_epoch, **extra)

    yield client, rotate, domain, tmp_path, owner
    for result in clients:
        result.close()
    server.shutdown()
    thread.join(timeout=3)
    server.server_close()


def test_real_shared_epoch_change_normalizes_stale_and_reattaches_read(service, monkeypatch):
    factory, rotate, domain, root, _ = service
    reader = factory()
    old_lease = reader._lease_id
    rotate()
    request = Mock(wraps=reader._request)
    monkeypatch.setattr(reader, "_request", request)
    assert reader.get_execution_request(root, "req-one")["request_id"] == "req-one"
    assert [call.args[0] for call in request.call_args_list] == ["/v1/call", "/v1/health", "/v1/client-leases/acquire", "/v1/call"]
    assert reader._owner_epoch == "epoch-two"
    assert reader._lease_id != old_lease
    assert domain.reads == 1


def test_real_shared_epoch_change_does_not_replay_mutation(service, monkeypatch):
    factory, rotate, domain, root, _ = service
    writer = factory()
    rotate()
    request = Mock(wraps=writer._request)
    monkeypatch.setattr(writer, "_request", request)
    with pytest.raises(AudiaGenticError, match="CON-AGSV-018"):
        writer.cancel_execution_request(root, "req-one")
    assert request.call_count == 1
    assert writer._lease_id is None
    assert domain.cancels == 0
    assert writer.cancel_execution_request(root, "req-one")["state"] == "cancelled"
    assert domain.cancels == 1
    assert writer._owner_epoch == "epoch-two"


def test_real_shared_active_borrowed_lease_remains_unauthorized(service):
    factory, _, domain, root, _ = service
    alice, bob = factory("alice"), factory("bob")
    borrowed = alice._lease_id
    bob._lease_id, bob._owner_epoch = borrowed, alice._owner_epoch
    with pytest.raises(AudiaGenticError, match="VAL-AGSV-005"):
        bob.get_execution_request(root, "req-one")
    # Authorization failures are not stale leases, and trigger no reattach.
    assert bob._lease_id == borrowed
    assert domain.reads == 0


def test_real_shared_cached_catalog_read_reattaches_after_epoch_change(service, monkeypatch):
    from audiagentic.components.agents.configuration import management

    factory, rotate, _, root, _ = service
    reader = factory()
    cards = [{"agent_id": "reviewer", "name": "Reviewer"}]
    catalog = Mock(return_value=cards)
    monkeypatch.setattr(management, "list_agent_definition_cards", catalog)
    rotate()
    request = Mock(wraps=reader._request)
    monkeypatch.setattr(reader, "_request", request)
    assert reader.list_agent_definition_cards(root) == cards
    assert [call.args[0] for call in request.call_args_list] == ["/v1/call", "/v1/health", "/v1/client-leases/acquire", "/v1/call"]
    assert reader._owner_epoch == "epoch-two"
    catalog.assert_called_once_with(root)
