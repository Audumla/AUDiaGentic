from __future__ import annotations

import json
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from audiagentic.components.agents.gateway.service.application import GatewayServiceApplication
from audiagentic.components.agents.gateway.service.contract import PROTOCOL_VERSION
from audiagentic.components.agents.gateway.service.http_transport import GatewayHTTPServer
from audiagentic.components.agents.gateway.service.shared_config import (
    SharedGatewayPrincipal,
    SharedGatewayServerConfig,
)
from audiagentic.foundation.system.managed_service import ManagedServiceStore
from audiagentic.foundation.system.managed_service_contracts import ServiceKey


class Application:
    def __init__(self):
        self.responses = {}

    def list_execution_requests(self, root, **kwargs):
        return [{"project": root.name}]

    def submit_execution_request(self, root, **kwargs):
        request_id = f"req_test_{len(self.responses)}"
        self.responses[root, request_id] = kwargs["prompt_body"]
        return {"request-id": request_id, "session-id": kwargs.get("session_id", "ses_shared")}

    def get_execution_response(self, root, request_id):
        return self.responses[root, request_id]


@pytest.fixture
def shared(tmp_path):
    projects = {}
    for name in ("one", "two"):
        projects[name] = tmp_path / name
        projects[name].mkdir()
    principals = []
    for name, grants in (("alice", {"one"}), ("bob", {"two"}), ("observer", {"one"})):
        token_file = tmp_path / f"{name}.token"
        token_file.write_text(f"token-{name}")
        actions = {"read"} if name == "observer" else {"read", "submit", "session"}
        principals.append(SharedGatewayPrincipal(name, token_file, frozenset(grants), frozenset(actions)))
    config = SharedGatewayServerConfig(server_id="test", port=0, service_root=tmp_path / "service", projects=projects, principals=tuple(principals))
    store = ManagedServiceStore(ServiceKey("gateway", "shared-test"), root=config.service_root)
    record = store.create(protocol_version=PROTOCOL_VERSION, owner_epoch="epoch-test")
    store.transition("running", expected_revision=record.revision, expected_epoch=record.owner_epoch)
    application = GatewayServiceApplication(Application(), store)
    server = GatewayHTTPServer(("127.0.0.1", 0), application, "local-secret", shared_config=config)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def request(path, body=None, token="token-alice"):
        req = Request(f"http://127.0.0.1:{server.server_port}{path}",
                      data=None if body is None else json.dumps(body).encode(),
                      headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        try:
            with urlopen(req, timeout=3) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            return error.code, json.load(error)

    yield request
    server.shutdown()
    thread.join(timeout=3)
    server.server_close()


def acquire(request, token="token-alice"):
    status, result = request("/shared/v1/client-leases/acquire", {
        "client-instance-id": "same-client", "ttl-seconds": 60, "protocol-version": PROTOCOL_VERSION,
    }, token)
    assert status == 200, result
    return result["result"]


def call(lease, **overrides):
    return {"operation": "list_execution_requests", "project-id": "one", "params": {},
            "protocol-version": PROTOCOL_VERSION, "owner-epoch": lease["owner-epoch"],
            "lease-id": lease["lease-id"], **overrides}


@pytest.mark.parametrize("path", ["/dashboard", "/dashboard/snapshot", "/v1/health", "/v1/call", "/shared/v1/health?extra=1"])
def test_shared_mode_excludes_legacy_and_unrecognized_routes(shared, path):
    assert shared(path)[0] == 400


def test_shared_health_auth_and_redaction(shared):
    assert shared("/shared/v1/health", token="local-secret")[0] == 401
    status, response = shared("/shared/v1/health")
    assert status == 200
    health = response["result"]
    assert health["server-id"] == "test"
    assert "endpoint" not in health and "lifetime-scope" not in health


def test_two_principals_project_scope_and_durable_lease_fence(shared):
    alice, bob = acquire(shared), acquire(shared, "token-bob")
    assert alice["lease-id"] != bob["lease-id"]
    assert shared("/shared/v1/call", call(alice))[1]["result"] == [{"project": "one"}]
    assert shared("/shared/v1/call", call(alice, **{"project-id": "two"}))[0] == 401
    assert shared("/shared/v1/call", call(alice, **{"project-id": "two"}), "token-bob")[0] == 401
    assert shared("/shared/v1/call", call(bob, **{"project-id": "two"}), "token-bob")[0] == 200
    for suffix, extra in (("renew", {"ttl-seconds": 60}), ("release", {})):
        body = {"lease-id": alice["lease-id"], "owner-epoch": alice["owner-epoch"], "protocol-version": PROTOCOL_VERSION, **extra}
        assert shared(f"/shared/v1/client-leases/{suffix}", body, "token-bob")[0] == 401


def test_project_read_grant_is_collaborative_but_not_mutation_authority(shared):
    alice = acquire(shared)
    submitted = shared("/shared/v1/call", call(alice, operation="submit_execution_request",
        params={"execution_profile_id": "test", "prompt_body": "creator output", "session_id": "ses_shared"}))[1]["result"]
    assert submitted["session-id"] == "ses_shared"
    observer = acquire(shared, "token-observer")
    assert shared("/shared/v1/call", call(observer), "token-observer")[0] == 200
    assert shared("/shared/v1/call", call(observer, operation="get_execution_response",
        params={"request_id": submitted["request-id"]}), "token-observer")[1]["result"] == "creator output"
    for operation in ("submit_execution_request", "cancel_execution_request", "close_execution_session"):
        assert shared("/shared/v1/call", call(observer, operation=operation), "token-observer")[0] == 401
    bob = acquire(shared, "token-bob")
    assert shared("/shared/v1/call", call(bob, operation="get_execution_response",
        params={"request_id": submitted["request-id"]}), "token-bob")[0] == 401


def test_shared_idempotency_and_default_identity_are_stable_and_principal_scoped(tmp_path):
    from audiagentic.components.agents.gateway.service.shared_ingress import SharedGatewayIngress

    token = tmp_path / "test.token"
    token.write_text("test-credential")
    alice = SharedGatewayPrincipal("alice", token, frozenset({"one"}), frozenset({"submit"}))
    bob = SharedGatewayPrincipal("bob", token, frozenset({"one"}), frozenset({"submit"}))
    ingress = SharedGatewayIngress(SharedGatewayServerConfig(server_id="test", port=0, service_root=tmp_path,
        projects={"one": tmp_path}, principals=(alice,)))
    def prepared(principal, lease_id, client_id):
        body = call({"lease-id": lease_id, "owner-epoch": "epoch"}, operation="submit_execution_request",
                    params={"metadata": {"idempotency_key": "job-1"}})
        return ingress.prepare_call(principal, body, client_instance_id=client_id)[2]
    first, repeated = prepared(alice, "lease-one", "client-one"), prepared(alice, "lease-two", "client-one")
    assert first == repeated
    other_client = prepared(alice, "lease-three", "client-two")
    assert first["logical_client_id"] != other_client["logical_client_id"]
    other_principal = prepared(bob, "lease-four", "client-one")
    assert first["logical_client_id"] != other_principal["logical_client_id"]
    assert first["metadata"]["idempotency_key"] != other_principal["metadata"]["idempotency_key"]


@pytest.mark.parametrize("overrides", [
    {"project-root": "caller-root"},
    {"operation": "service_stop"},
    {"operation": "purge_execution_sessions"},
    {"operation": "submit_execution_request", "params": {"component_profile": "caller"}},
    {"operation": "submit_execution_request", "params": {"metadata": {"environment": {"A": "B"}}}},
    {"operation": "resume_execution_session", "params": {"model_id": "caller"}},
])
def test_shared_rejects_client_authority_and_operator_mutation(shared, overrides):
    assert shared("/shared/v1/call", call(acquire(shared), **overrides))[0] in {400, 401}
