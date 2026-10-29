"""Shared HTTPS wire contract for the existing standalone client."""
from __future__ import annotations

import io
import json
import ssl
import time
from email.message import Message
from pathlib import Path
from unittest.mock import Mock
from urllib.error import HTTPError, URLError
from urllib.request import build_opener
from urllib.response import addinfourl

import pytest

from audiagentic.components.agents.gateway import remote_client as remote
from audiagentic.components.agents.gateway.service.contract import PROTOCOL_VERSION
from audiagentic.foundation.contracts.errors import AudiaGenticError


class Response:
    def __init__(self, result):
        self.result = result

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self):
        return json.dumps({"ok": True, "result": self.result}).encode()


def shared(**kwargs):
    return remote.StandaloneGatewayClient(
        "https://gateway.example:9443", "secret", shared_server_id="server-a",
        shared_project_id="project-a", **kwargs,
    )


def health(**updates):
    return {"protocol-version": PROTOCOL_VERSION, "server-id": "server-a", "owner-epoch": "epoch-a", "projects": ["project-a"], **updates}


@pytest.mark.parametrize("endpoint", [
    "http://gateway.example:9443", "https://user:pass@gateway.example",
    "https://gateway.example/path", "https://gateway.example?query",
    "https://gateway.example#fragment", "https://gateway.example:bad",
    "https://gateway.example:0", "https://", "https://gateway.example\\evil",
    "https://gateway.example\n", "https://gateway.example?", "https://gateway.example#",
])
def test_shared_rejects_unsafe_origins(endpoint):
    with pytest.raises(AudiaGenticError, match="VAL-AGSV-016"):
        remote.StandaloneGatewayClient(endpoint, "secret", shared_server_id="server-a", shared_project_id="project-a")


@pytest.mark.parametrize("server,project", [(None, "project"), ("server", None), ("", "project"), ("SERVER", "project"), ("server", "../project")])
def test_shared_requires_both_safe_ids(server, project):
    with pytest.raises(AudiaGenticError, match="VAL-AGSV-016"):
        remote.StandaloneGatewayClient("https://gateway.example", "secret", shared_server_id=server, shared_project_id=project)


def test_shared_uses_supplied_trust_context(monkeypatch):
    context = ssl.create_default_context()
    constructor = Mock(wraps=remote.HTTPSHandler)
    monkeypatch.setattr(remote, "HTTPSHandler", constructor)
    shared(ssl_context=context)
    constructor.assert_called_once_with(context=context)


@pytest.mark.parametrize("verify", [False, True])
def test_shared_refuses_disabled_tls_verification(verify):
    context = ssl.create_default_context()
    context.check_hostname = False
    if not verify:
        context.verify_mode = ssl.CERT_NONE
    with pytest.raises(AudiaGenticError, match="VAL-AGSV-016"):
        shared(ssl_context=context)


def test_full_shared_lease_and_call_wire_shape(monkeypatch):
    client = shared(client_instance_id="physical", logical_client_id="logical")
    requests = []
    results = iter([health(), {"lease-id": "lease-a", "owner-epoch": "epoch-a"}, {"state": "queued"}, {"expires-at": "later"}, {"state": "done"}, {}])

    def open_request(request, **kwargs):
        requests.append((request, kwargs))
        return Response(next(results))

    monkeypatch.setattr(client._shared_opener, "open", open_request)
    assert client.submit_execution_request(Path("/private/client/root"), prompt_body="hello")["state"] == "queued"
    client._renew_at = 0
    assert client.get_execution_request(Path("/another/client/root"), "req-a")["state"] == "done"
    client.close()
    assert [r.full_url for r, _ in requests] == [
        "https://gateway.example:9443/shared/v1/" + suffix for suffix in
        ["health", "client-leases/acquire", "call", "client-leases/renew", "call", "client-leases/release"]
    ]
    assert requests[0][0].method == "GET"
    assert requests[0][0].data is None
    for request, _ in requests:
        assert request.get_header("Authorization") == "Bearer secret"
        if request.data:
            body = json.loads(request.data)
            assert "server-id" not in body
            assert body["protocol-version"] == PROTOCOL_VERSION
            assert "project-root" not in body
            assert "private/client" not in request.data.decode()
    call = json.loads(requests[2][0].data)
    assert set(call) == {"protocol-version", "owner-epoch", "lease-id", "project-id", "operation", "params"}
    assert call["project-id"] == "project-a"
    assert call["params"]["logical_client_id"] == "logical"
    assert "component_profile" not in call["params"]
    assert requests[-1][1]["timeout"] == 1.0


@pytest.mark.parametrize("updates,code", [({"server-id": "wrong"}, "VAL-AGSV-014"), ({"server-id": None}, "VAL-AGSV-014"), ({"protocol-version": "future"}, "VAL-AGSV-013"), ({"owner-epoch": ""}, "NET-AGSV-003")])
def test_health_handshake_rejects_before_acquire(monkeypatch, updates, code):
    client = shared()
    transport = Mock(return_value=Response(health(**updates)))
    monkeypatch.setattr(client._shared_opener, "open", transport)
    with pytest.raises(AudiaGenticError, match=code):
        client.connect()
    assert transport.call_count == 1
    assert client._lease_id is None


@pytest.mark.parametrize("failure", [URLError("ambiguous"), TimeoutError("ambiguous"), HTTPError("https://gateway.example", 409, "conflict", {}, io.BytesIO(json.dumps({"error-code": "CON-AGSV-018", "error-kind": "conflict", "message": "expired"}).encode()))])
def test_shared_call_never_replays(monkeypatch, failure):
    client = shared()
    client._lease_id, client._owner_epoch = "lease-a", "epoch-a"
    client._renew_at = time.monotonic() + 100
    transport = Mock(side_effect=failure)
    monkeypatch.setattr(client._shared_opener, "open", transport)
    with pytest.raises(AudiaGenticError):
        client.cancel_execution_request(Path("/private"), "req-a")
    assert transport.call_count == 1


def test_shared_health_retry_is_bounded_and_read_only(monkeypatch):
    client = shared()
    transport = Mock(side_effect=[URLError("transient"), Response(health())])
    monkeypatch.setattr(client._shared_opener, "open", transport)
    monkeypatch.setattr(remote.time, "sleep", lambda _: None)
    assert client.health()["server-id"] == "server-a"
    assert transport.call_count == 2
    assert client._lease_id is None


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_redirects_are_not_followed_or_forwarded(monkeypatch, status):
    requests = []

    class FakeHTTPS(remote.HTTPSHandler):
        def https_open(self, request):
            requests.append(request)
            headers = Message()
            headers["Location"] = "https://attacker.example/collect"
            response = addinfourl(io.BytesIO(b"redirect"), headers, request.full_url, status)
            response.msg = "redirect"
            return response

    client = shared()
    # Exercise urllib's real redirect processing with only socket I/O replaced.
    client._shared_opener = build_opener(FakeHTTPS(), remote._RejectRedirects())
    with pytest.raises(AudiaGenticError, match="redirects are forbidden"):
        client.health()
    assert len(requests) == 1
    assert requests[0].host == "gateway.example:9443"


@pytest.mark.parametrize("field", ["workspace_name", "component_profile", "execution_context_fingerprint", "provider_chat_url", "unexpected"])
def test_shared_rejects_local_submission_fields_before_network(monkeypatch, field):
    client = shared()
    transport = Mock()
    monkeypatch.setattr(client._shared_opener, "open", transport)
    with pytest.raises(AudiaGenticError, match="VAL-AGSV-022"):
        client.submit_execution_request(Path("/private"), **{field: "private-local-value"})
    transport.assert_not_called()


@pytest.mark.parametrize("metadata", [[], "invalid", {"provider_id": "local"}, {"client-icon": "local"}, {"workspace_name": "private"}])
def test_shared_rejects_metadata_outside_contract_before_network(monkeypatch, metadata):
    client = shared()
    transport = Mock()
    monkeypatch.setattr(client._shared_opener, "open", transport)
    with pytest.raises(AudiaGenticError, match="VAL-AGSV-022"):
        client.submit_execution_request(Path("/private"), metadata=metadata)
    transport.assert_not_called()


def test_shared_metadata_and_explicit_alias_preserved_root_not_resolved(monkeypatch):
    client = shared()
    client._lease_id, client._owner_epoch = "lease-a", "epoch-a"
    client._renew_at = time.monotonic() + 100
    transport = Mock(return_value=Response({"state": "queued"}))
    monkeypatch.setattr(client._shared_opener, "open", transport)
    monkeypatch.setenv("AUDIAGENTIC_COMPONENT_PROFILE", "must-not-leak")
    metadata = {"schema_version": 1, "idempotency_key": "stable", "correlation_id": "trace"}
    class NoLocalRoot:
        def expanduser(self):
            raise AssertionError("client root accessed")
    client.submit_execution_request(NoLocalRoot(), metadata=metadata, logical_client_id="editor-a", prompt_body="hello")
    params = json.loads(transport.call_args.args[0].data)["params"]
    assert params == {"metadata": metadata, "prompt_body": "hello", "logical_client_id": "editor-a"}
    assert metadata == {"schema_version": 1, "idempotency_key": "stable", "correlation_id": "trace"}


def test_local_wire_still_uses_root_and_existing_transport(monkeypatch, tmp_path):
    client = remote.StandaloneGatewayClient("http://127.0.0.1:9000", "secret")
    client._lease_id, client._owner_epoch = "lease-a", "epoch-a"
    client._renew_at = time.monotonic() + 100
    transport = Mock(return_value=Response({"state": "queued"}))
    monkeypatch.setattr(remote, "urlopen", transport)
    client.submit_execution_request(tmp_path, prompt_body="hello", component_profile="local")
    request = transport.call_args.args[0]
    body = json.loads(request.data)
    assert request.full_url == "http://127.0.0.1:9000/v1/call"
    assert body["project-root"] == str(tmp_path.resolve())
    assert "project-id" not in body
    assert body["params"]["component_profile"] == "local"
    assert body["params"]["logical_client_id"] == client._logical_client_id


def test_shared_acquire_not_retried_after_ambiguous_failure(monkeypatch):
    client = shared()
    transport = Mock(side_effect=[Response(health()), URLError("ambiguous acquire")])
    monkeypatch.setattr(client._shared_opener, "open", transport)
    with pytest.raises(AudiaGenticError, match="NET-AGSV-002"):
        client.connect()
    assert transport.call_count == 2
    assert client._lease_id is None



def test_shared_default_identity_survives_lease_changes(monkeypatch):
    client = shared()
    transport = Mock(return_value=Response({"state": "queued"}))
    monkeypatch.setattr(client._shared_opener, "open", transport)
    for lease in ("lease-a", "lease-b"):
        client._lease_id, client._owner_epoch = lease, "epoch-a"
        client._renew_at = time.monotonic() + 100
        client.submit_execution_request(Path("/private"), prompt_body="hello")
    bodies = [json.loads(call.args[0].data) for call in transport.call_args_list]
    assert [body["lease-id"] for body in bodies] == ["lease-a", "lease-b"]
    assert [body["params"]["logical_client_id"] for body in bodies] == [client._logical_client_id] * 2
    assert shared()._logical_client_id != client._logical_client_id



@pytest.mark.parametrize("projects", [None, [], ["other-project"], "project-a", {"project-a": "/server/path"}, ["project-a", 123]])
@pytest.mark.parametrize("attach", [False, True])
def test_shared_project_grant_required_for_health_and_connect(monkeypatch, projects, attach):
    client = shared()
    transport = Mock(return_value=Response(health(projects=projects)))
    monkeypatch.setattr(client._shared_opener, "open", transport)
    with pytest.raises(AudiaGenticError, match="VAL-AGSV-005"):
        (client.connect if attach else client.health)()
    assert transport.call_count == 1
    assert client._lease_id is None
    assert transport.call_args.args[0].full_url.endswith("/shared/v1/health")


def test_shared_missing_project_grants_fail_closed(monkeypatch):
    client = shared()
    payload = health()
    del payload["projects"]
    transport = Mock(return_value=Response(payload))
    monkeypatch.setattr(client._shared_opener, "open", transport)
    with pytest.raises(AudiaGenticError, match="VAL-AGSV-005"):
        client.health()
    assert transport.call_count == 1
