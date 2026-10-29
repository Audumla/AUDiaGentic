"""Shared HTTP compact payloads reuse the MCP projection without changing local APIs."""
from __future__ import annotations

import copy
import json
import threading
from urllib.request import Request, urlopen

import pytest

from audiagentic.components.agents.gateway.evidence_projection import (
    project_public_gateway_request,
    project_public_gateway_session,
)
from audiagentic.components.agents.gateway.service.application import GatewayServiceApplication
from audiagentic.components.agents.gateway.service.contract import PROTOCOL_VERSION
from audiagentic.components.agents.gateway.service.http_transport import GatewayHTTPServer
from audiagentic.components.agents.gateway.service.shared_config import (
    SharedGatewayPrincipal,
    SharedGatewayServerConfig,
)
from audiagentic.components.agents.mcp import gateway_mcp
from audiagentic.components.agents.status.task_status_v4 import project_task_status_v4
from audiagentic.foundation.system.managed_service import ManagedServiceStore
from audiagentic.foundation.system.managed_service_contracts import ServiceKey


class Application:
    def __init__(self):
        self.records = {}
        self.explicit = {"history": [{"event": "evidence"}], "diagnostics": {"classification": "explicit"}, "text": "exact response"}

    def record(self, request_id="req-mutation"):
        return {
            "request-id": request_id, "session-id": "ses-one", "state": "queued", "revision": 0,
            "prompt-body": "PRIVATE PROMPT" * 500, "runtime": {"pid": 123},
            "metadata": {"internal": "secret"}, "provider-metadata": {"chat-url": "private"},
            "manifest": {"project-root": "/private/server"}, "history": [{"private": True}],
            "execution-profile-id": "private-profile", "profile-diagnostics": None,
            "null-field": None, "reason": None, "warnings": ["notice"],
        }

    def submit_execution_request(self, root, **kwargs):
        record = self.record(f"req-{len(self.records)}")
        self.records[record["request-id"]] = record
        return copy.deepcopy(record)

    def cancel_execution_request(self, *args, **kwargs):
        return self.record()

    recover_execution_request = cancel_execution_request
    complete_execution_from_provider = cancel_execution_request
    close_execution_session = cancel_execution_request
    resume_execution_session = cancel_execution_request

    def list_execution_sessions(self, *args, **kwargs):
        return [self.record()]

    def list_execution_requests(self, *args, **kwargs):
        return [project_task_status_v4(self.record())]

    def get_execution_diagnostics(self, *args, **kwargs):
        return self.explicit

    get_execution_evidence = get_execution_diagnostics
    get_execution_observations = get_execution_diagnostics
    get_execution_response_payload = get_execution_diagnostics

    def get_execution_response(self, *args, **kwargs):
        return self.explicit["text"]

    get_execution_failure_response = get_execution_response


@pytest.fixture
def wire(tmp_path):
    servers = []

    def start(shared_mode=True):
        application = Application()
        token = tmp_path / "alice.token"
        token.write_text("token-alice")
        bob_token = tmp_path / "bob.token"
        bob_token.write_text("token-bob")
        store = ManagedServiceStore(ServiceKey("gateway", f"compact-{len(servers)}"), root=tmp_path / f"service-{len(servers)}")
        record = store.create(protocol_version=PROTOCOL_VERSION, owner_epoch="epoch")
        store.transition("running", expected_revision=record.revision, expected_epoch=record.owner_epoch)
        config = SharedGatewayServerConfig(server_id="test", port=0, service_root=store.root, projects={"one": tmp_path}, principals=tuple(
            SharedGatewayPrincipal(name, path, frozenset({"one"}), frozenset({"read", "submit", "cancel", "session"}))
            for name, path in (("alice", token), ("bob", bob_token))
        )) if shared_mode else None
        owner = GatewayServiceApplication(application, store)
        server = GatewayHTTPServer(("127.0.0.1", 0), owner, "local-token", shared_config=config)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        servers.append((server, thread))
        prefix = "/shared/v1" if shared_mode else "/v1"

        def post(suffix, body, credential="token-alice"):
            request = Request(f"http://127.0.0.1:{server.server_port}{prefix}/{suffix}", data=json.dumps(body).encode(), headers={"Authorization": f"Bearer {credential}", "Content-Type": "application/json"})
            with urlopen(request, timeout=3) as response:
                envelope = json.load(response)
            assert envelope["ok"] is True
            return envelope["result"]

        def acquire(credential="token-alice"):
            return post("client-leases/acquire", {"client-instance-id": credential, "ttl-seconds": 60, "protocol-version": PROTOCOL_VERSION}, credential)

        def call(operation, params=None, credential="token-alice", lease=None):
            lease = lease or acquire(credential)
            scope = {"project-id": "one"} if shared_mode else {"project-root": str(tmp_path)}
            return post("call", {"operation": operation, "params": params or {}, "protocol-version": PROTOCOL_VERSION, "owner-epoch": lease["owner-epoch"], "lease-id": lease["lease-id"], **scope}, credential)

        return application, call, owner

    yield start
    for server, thread in servers:
        server.shutdown()
        thread.join(timeout=3)
        server.server_close()


def test_shared_submit_two_principals_compact_ids_and_mcp_parity(wire, monkeypatch):
    application, call, _ = wire()
    for principal in ("alice", "bob"):
        result = call("submit_execution_request", {"execution_profile_id": "test", "prompt_body": "test"}, f"token-{principal}")
        raw = application.records[result["request-id"]]
        assert result == {"request-id": raw["request-id"], "session-id": "ses-one", "state": "queued", "revision": 0, "warnings": ["notice"]}
        assert len(json.dumps(result)) < 250
        assert len(json.dumps(raw)) > 4000
        assert all(value is not None for value in result.values())
        assert not ({"prompt-body", "runtime", "metadata", "provider-metadata", "manifest", "history", "profile-diagnostics"} & result.keys())
        monkeypatch.setattr(gateway_mcp, "project_root_from_env", lambda: None)
        monkeypatch.setattr(gateway_mcp, "call_gateway_method", lambda *args, **kwargs: raw)
        assert gateway_mcp.agent_task_submit("test") == result
        assert gateway_mcp.project_public_gateway_request is project_public_gateway_request
        assert not hasattr(gateway_mcp, "_request_dto")
    assert set(application.records) == {"req-0", "req-1"}
    assert all(record["metadata"] == {"internal": "secret"} for record in application.records.values())


@pytest.mark.parametrize("operation,params", [
    ("cancel_execution_request", {"request_id": "req-mutation"}),
    ("recover_execution_request", {"request_id": "req-mutation", "action": "reconcile"}),
    ("complete_execution_from_provider", {"request_id": "req-mutation"}),
])
def test_shared_request_mutations_use_one_projection(wire, operation, params):
    application, call, _ = wire()
    assert call(operation, params) == project_public_gateway_request(application.record())


@pytest.mark.parametrize("operation,params", [
    ("close_execution_session", {"session_id": "ses-one"}),
    ("resume_execution_session", {"source_session_id": "ses-one", "control_id": "control-one"}),
    ("list_execution_sessions", {}),
])
def test_shared_session_mutations_and_list_use_mcp_projection(wire, operation, params):
    application, call, _ = wire()
    expected = project_public_gateway_session(application.record())
    assert call(operation, params) == ([expected] if operation.startswith("list_") else expected)
    assert gateway_mcp.project_public_gateway_session is project_public_gateway_session


def test_shared_request_list_preserves_existing_v4_projection(wire):
    application, call, _ = wire()
    expected = application.list_execution_requests()
    assert call("list_execution_requests") == expected
    assert expected[0]["lifecycle"] == "pending"
    assert expected[0]["activity_seq"] == 0
    assert "history" not in expected[0]


@pytest.mark.parametrize("operation", ["get_execution_diagnostics", "get_execution_evidence", "get_execution_observations", "get_execution_response_payload", "get_execution_response", "get_execution_failure_response"])
def test_explicit_shared_reads_preserve_payloads(wire, operation):
    application, call, _ = wire()
    expected = application.explicit["text"] if operation in {"get_execution_response", "get_execution_failure_response"} else application.explicit
    assert call(operation, {"request_id": "req-mutation"}) == expected


def test_local_http_and_application_keep_full_record_contract(wire, tmp_path):
    application, call, owner = wire(shared_mode=False)
    result = call("submit_execution_request", {"execution_profile_id": "test", "prompt_body": "test"}, "local-token")
    assert result == application.records[result["request-id"]]
    assert result["prompt-body"].startswith("PRIVATE PROMPT")
    lease = owner.acquire_client("direct-client", ttl_seconds=60, protocol_version=PROTOCOL_VERSION)
    direct = owner.invoke("submit_execution_request", str(tmp_path), {"execution_profile_id": "test", "prompt_body": "test"}, protocol_version=PROTOCOL_VERSION, owner_epoch=lease["owner-epoch"], lease_id=lease["lease-id"])
    assert direct == application.records[direct["request-id"]]


def test_canonical_request_projection_bounds_warnings_and_keeps_false_zero():
    raw = {"request_id": "req", "session_id": "ses", "revision": 0, "outcome": False, "reason": None, "warnings": ["w" * 300] * 20 + [{"private": True}]}
    assert project_public_gateway_request(raw) == {"request-id": "req", "session-id": "ses", "revision": 0, "outcome": False, "warnings": ["w" * 256] * 16}
