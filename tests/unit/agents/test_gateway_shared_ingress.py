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

    def request(path, body=None, token="token-alice", *, headers=None):
        req = Request(f"http://127.0.0.1:{server.server_port}{path}",
                      data=None if body is None else json.dumps(body).encode(),
                      headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json", **(headers or {})})
        try:
            with urlopen(req, timeout=3) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            return error.code, json.load(error)

    request.application = application
    request.server = server
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


def node_params():
    return {
        "agent_id": "reviewer", "prompt_body": "inspect caller files",
        "node_id": "local-node", "workspace_id": "working-tree",
        "source_workspace": {
            "identity": {"version": 1, "source-node-id": "local-node",
                         "workspace-id": "working-tree", "access-mode": "read-write",
                         "binding-sha256": "a" * 64},
            # An opaque foreign locator: ingress must never resolve or inspect it.
            "caller-root": "/unavailable-on-gateway/caller-workspace",
        },
    }


SOURCE_HEADER = {"X-AUDiaGentic-Source-Node-Token": "node-credential"}


def test_node_submission_is_private_context_not_ordinary_provider_submission(shared):
    from audiagentic.components.agents.gateway.node.admission_contract import NodeSubmissionContext

    calls = []

    class Admission:
        def submit(self, root, **kwargs):
            calls.append((root, kwargs))
            return {"request-id": "req_test_node", "state": "queued",
                    "private-source-token": "must-not-leak"}

    shared.application._node_admission = Admission()
    lease = acquire(shared)
    status, response = shared("/shared/v1/call", call(
        lease, operation="submit_execution_request", params=node_params()), headers=SOURCE_HEADER)
    assert status == 200, response
    assert response["result"] == {"request-id": "req_test_node", "state": "queued"}
    root, invocation = calls.pop()
    assert root.name == "one"
    context = invocation["context"]
    assert type(context) is NodeSubmissionContext
    assert (context.principal_id, context.server_id, context.server_project_id) == ("alice", "test", "one")
    assert context.source_node_token == "node-credential"
    assert context.caller_root == "/unavailable-on-gateway/caller-workspace"
    assert "node-credential" not in repr(context)
    assert context.caller_root not in repr(context)
    assert invocation["owner_epoch"] == lease["owner-epoch"]
    assert not {"node_id", "workspace_id", "source_workspace"}.intersection(invocation["arguments"])
    assert invocation["arguments"]["prompt_body"] == "inspect caller files"
    assert shared.application._application.responses == {}


def test_node_submission_disabled_does_not_fall_back_to_server_execution(shared):
    status, response = shared("/shared/v1/call", call(
        acquire(shared), operation="submit_execution_request", params=node_params()), headers=SOURCE_HEADER)
    assert status == 400, response
    assert "Node execution is not enabled" in json.dumps(response)
    assert shared.application._application.responses == {}


@pytest.mark.parametrize("missing", ["node_id", "workspace_id", "source_workspace", "credential"])
def test_node_submission_requires_all_context_and_header(shared, missing):
    params = node_params()
    headers = SOURCE_HEADER
    if missing == "credential":
        headers = {}
    else:
        params.pop(missing)
    status, _ = shared("/shared/v1/call", call(
        acquire(shared), operation="submit_execution_request", params=params), headers=headers)
    assert status == 400
    assert shared.application._application.responses == {}


@pytest.mark.parametrize("route", ["health", "lease", "read"])
def test_source_credential_is_rejected_outside_node_submission(shared, route):
    lease = acquire(shared)
    path, body = {
        "health": ("/shared/v1/health", None),
        "lease": ("/shared/v1/client-leases/acquire", {"client-instance-id": "other"}),
        "read": ("/shared/v1/call", call(lease)),
    }[route]
    assert shared(path, body, headers=SOURCE_HEADER)[0] == 400


def test_node_submission_cannot_use_another_principals_lease(shared):
    lease = acquire(shared, "token-bob")
    assert shared("/shared/v1/call", call(lease, operation="submit_execution_request",
        params=node_params()), headers=SOURCE_HEADER)[0] == 401


def test_node_admission_respects_gateway_drain(shared):
    lease = acquire(shared)

    class UnexpectedAdmission:
        def submit(self, *args, **kwargs):
            pytest.fail("draining gateway must not reach node admission")

    shared.application._node_admission = UnexpectedAdmission()
    store = shared.application._service_store
    record = store.read()
    store.transition("draining", expected_revision=record.revision, expected_epoch=record.owner_epoch)
    status, response = shared("/shared/v1/call", call(
        lease, operation="submit_execution_request", params=node_params()), headers=SOURCE_HEADER)
    assert status == 400, response
    assert "CON-AGSV-029" in json.dumps(response)


@pytest.mark.parametrize("header,value", [
    ("Authorization", "Bearer token-alice"),
    ("X-AUDiaGentic-Source-Node-Token", "node-credential"),
])
def test_duplicate_authentication_headers_are_rejected(shared, header, value):
    from http.client import HTTPConnection

    lease = acquire(shared)
    body = json.dumps(call(lease, operation="submit_execution_request", params=node_params()))
    connection = HTTPConnection("127.0.0.1", shared.server.server_port, timeout=3)
    try:
        connection.putrequest("POST", "/shared/v1/call")
        connection.putheader("Authorization", "Bearer token-alice")
        connection.putheader("X-AUDiaGentic-Source-Node-Token", "node-credential")
        connection.putheader(header, value)
        connection.putheader("Content-Length", str(len(body.encode())))
        connection.endheaders(body.encode())
        response = connection.getresponse()
        assert response.status == 400, response.read()
    finally:
        connection.close()


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


def test_mcp_definition_discovery_uses_server_catalog_not_client_catalog(shared, tmp_path, monkeypatch):
    from audiagentic.components.agents.configuration import management
    from audiagentic.components.agents.gateway import client as client_module
    from audiagentic.components.agents.gateway.remote_client import StandaloneGatewayClient
    from audiagentic.components.agents.mcp import gateway_mcp

    local_root = tmp_path / "client-machine"
    local_definitions = [{"agent_id": "local-only", "execution_profile_id": "local-secret"}]
    server_definitions = [{
        "agent_id": "server-reviewer", "name": "Server Reviewer",
        "description": "Server discovery", "advertised_skills": ["review"],
        "execution_profile_id": "server-private", "prompt_id": "secret-prompt",
        "role_ids": ["private-role"], "internal": True,
    }]
    reads = []
    def catalog(root):
        reads.append(root)
        if root == local_root:
            raise AssertionError(f"client catalog must not be read: {local_definitions}")
        assert root == tmp_path / "one"
        return server_definitions

    monkeypatch.setattr(management, "list_agent_definitions", catalog)
    remote = StandaloneGatewayClient(
        "https://server.example", "token-alice",
        shared_server_id="test", shared_project_id="one",
    )
    calls = []
    def transport(path, body, **kwargs):
        calls.append((path, body))
        status, payload = shared("/shared" + path, body)
        assert status == 200, payload
        return payload["result"]

    monkeypatch.setattr(remote, "_request", transport)
    monkeypatch.setattr(client_module, "get_gateway_client", lambda root: remote)
    monkeypatch.setattr(gateway_mcp, "project_root_from_env", lambda: local_root)
    result = gateway_mcp.agent_task_list_definitions()
    assert result == [{
        "agent_id": "server-reviewer", "name": "Server Reviewer",
        "description": "Server discovery", "skills": [{"id": "review", "name": "review"}],
    }]
    assert reads == [tmp_path / "one"]
    operation = [body for path, body in calls if path == "/v1/call"][0]
    assert operation["operation"] == "list_agent_definition_cards"
    assert operation["params"] == {}
    assert operation["project-id"] == "one"
    assert "project-root" not in operation
    assert "server-private" not in json.dumps(result)
    assert "secret-prompt" not in json.dumps(result)
    remote.close()


def test_definition_discovery_requires_project_read_grant_and_no_parameters(shared, monkeypatch):
    from audiagentic.components.agents.configuration import management
    monkeypatch.setattr(management, "list_agent_definitions", lambda root: [{"agent_id": "server-only"}])
    observer = acquire(shared, "token-observer")
    body = call(observer, operation="list_agent_definition_cards")
    status, payload = shared("/shared/v1/call", body, "token-observer")
    assert status == 200
    assert payload["result"] == [{"agent_id": "server-only"}]
    assert shared("/shared/v1/call", call(observer, operation="list_agent_definition_cards",
        **{"project-id": "two"}), "token-observer")[0] == 401
    assert shared("/shared/v1/call", call(observer, operation="list_agent_definition_cards",
        params={"include_config": True}), "token-observer")[0] == 400


# --- SH60c: Work acceptance takes its identity from the lease, never from the body ---------------------


def _work_app(shared):
    seen = []

    def accept(root, context_id, message, *, delivery_identity, work_id=None, intent=None):
        seen.append({"root": root, "context": context_id, "message": message, "identity": delivery_identity})
        return {"work_id": "work_1", "replayed": False}

    def wait(root, work_id, timeout_seconds=None):
        seen.append({"wait": work_id, "timeout": timeout_seconds})
        return {"wait-outcome": "timeout", "work": {"work_id": work_id}}

    shared.application._application.accept_agent_work_message = accept
    shared.application._application.wait_agent_work = wait
    return seen


def _accept(lease, **params):
    base = {"context_id": "ctx_1", "message": {"message_id": "m1", "text": "hi"}, "protocol": "a2a"}
    return call(lease, operation="accept_agent_work_message", params={**base, **params})


def test_work_acceptance_identity_comes_from_the_authenticated_lease(shared, tmp_path):
    seen = _work_app(shared)
    lease = acquire(shared)
    status, response = shared("/shared/v1/call", _accept(lease))
    assert status == 200, response
    identity = seen[0]["identity"]
    assert (identity["principal"], identity["protocol"], identity["subject"]) == ("alice", "a2a", None)
    assert identity["project_id"]  # the served root's declared identity, not a caller value


def test_a_caller_cannot_assert_a_delivery_identity_or_an_unknown_protocol(shared):
    _work_app(shared)
    lease = acquire(shared)
    status, _ = shared("/shared/v1/call", _accept(lease, delivery_identity={"principal": "root"}))
    assert status >= 400
    status, _ = shared("/shared/v1/call", _accept(lease, protocol="made-up"))
    assert status >= 400


def test_work_acceptance_needs_submit_and_the_project_grant(shared):
    seen = _work_app(shared)
    observer = acquire(shared, "token-observer")
    status, _ = shared("/shared/v1/call", _accept(observer), token="token-observer")
    assert status == 403 or status >= 400
    bob = acquire(shared, "token-bob")
    status, _ = shared("/shared/v1/call", _accept(bob), token="token-bob")  # bob is granted project two only
    assert status >= 400 and not seen


def test_waiting_on_work_is_a_read_and_returns_the_non_terminal_state(shared):
    seen = _work_app(shared)
    observer = acquire(shared, "token-observer")
    status, response = shared("/shared/v1/call", call(
        observer, operation="wait_agent_work", params={"work_id": "work_1", "timeout_seconds": 1}),
        token="token-observer")
    assert status == 200, response
    assert response["result"]["wait-outcome"] == "timeout" and seen == [{"wait": "work_1", "timeout": 1}]
