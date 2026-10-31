"""Shared stale-lease recovery retries reads only and never replays mutations."""
from __future__ import annotations

import io
import json
import time
from pathlib import Path
from unittest.mock import Mock
from urllib.error import HTTPError, URLError

import pytest

from audiagentic.components.agents.gateway.remote_client import StandaloneGatewayClient
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


def stale():
    return HTTPError("https://gateway.example/shared/v1/call", 409, "stale", {}, io.BytesIO(json.dumps({"error-code": "CON-AGSV-018", "error-kind": "conflict", "message": "stale lease"}).encode()))


def health(**updates):
    return Response({"server-id": "server", "protocol-version": PROTOCOL_VERSION, "projects": ["project"], "owner-epoch": "new-epoch", **updates})


@pytest.fixture
def client():
    client = StandaloneGatewayClient("https://gateway.example", "token", shared_server_id="server", shared_project_id="project")
    client._lease_id = "old-lease"
    client._owner_epoch = "old-epoch"
    client._renew_at = time.monotonic() + 100
    return client


def attach_transport(monkeypatch, client, outcomes):
    transport = Mock(side_effect=outcomes)
    monkeypatch.setattr(client._shared_opener, "open", transport)
    return transport


def paths(transport):
    return [call.args[0].selector for call in transport.call_args_list]


def test_old_lease_status_reconnects_once_through_health(monkeypatch, client):
    transport = attach_transport(monkeypatch, client, [stale(), health(), Response({"lease-id": "new-lease", "owner-epoch": "new-epoch"}), Response({"request_id": "req", "lifecycle": "active"})])
    assert client.get_execution_request(Path("/private"), "req")["lifecycle"] == "active"
    assert paths(transport) == ["/shared/v1/call", "/shared/v1/health", "/shared/v1/client-leases/acquire", "/shared/v1/call"]
    first, last = [json.loads(transport.call_args_list[index].args[0].data) for index in (0, 3)]
    assert first["lease-id"] == "old-lease"
    assert last["lease-id"] == "new-lease"
    assert last["owner-epoch"] == "new-epoch"
    assert first["project-id"] == last["project-id"] == "project"


@pytest.mark.parametrize("operation,params", [
    ("submit_execution_request", {"prompt_body": "hello"}),
    ("cancel_execution_request", {"request_id": "req"}),
    ("recover_execution_request", {"request_id": "req", "action": "reconcile"}),
    ("complete_execution_from_provider", {"request_id": "req"}),
    ("close_execution_session", {"session_id": "ses"}),
    ("resume_execution_session", {"source_session_id": "ses", "control_id": "control"}),
])
def test_stale_mutation_clears_lease_without_replay_next_explicit_call_attaches(monkeypatch, client, operation, params):
    transport = attach_transport(monkeypatch, client, [stale(), health(), Response({"lease-id": "new-lease", "owner-epoch": "new-epoch"}), Response({"state": "accepted"})])
    with pytest.raises(AudiaGenticError, match="CON-AGSV-018"):
        client._call(operation, Path("/private"), params)
    assert transport.call_count == 1
    assert client._lease_id is None and client._owner_epoch is None and client._renew_at == 0
    assert client._call(operation, Path("/private"), params) == {"state": "accepted"}
    assert paths(transport) == ["/shared/v1/call", "/shared/v1/health", "/shared/v1/client-leases/acquire", "/shared/v1/call"]


def test_second_stale_read_is_not_retried_and_invalidates_new_lease(monkeypatch, client):
    transport = attach_transport(monkeypatch, client, [stale(), health(), Response({"lease-id": "new-lease", "owner-epoch": "new-epoch"}), stale()])
    with pytest.raises(AudiaGenticError, match="CON-AGSV-018"):
        client.get_execution_request(Path("/private"), "req")
    assert transport.call_count == 4
    assert client._lease_id is None


@pytest.mark.parametrize("updates,code", [({"server-id": "wrong"}, "VAL-AGSV-014"), ({"projects": []}, "VAL-AGSV-005"), ({"protocol-version": "wrong"}, "VAL-AGSV-013")])
def test_restart_read_must_repeat_identity_protocol_and_grant_checks(monkeypatch, client, updates, code):
    transport = attach_transport(monkeypatch, client, [stale(), health(**updates)])
    with pytest.raises(AudiaGenticError, match=code):
        client.get_execution_request(Path("/private"), "req")
    assert paths(transport) == ["/shared/v1/call", "/shared/v1/health"]
    assert client._lease_id is None


@pytest.mark.parametrize("failure", [URLError("ambiguous"), TimeoutError("ambiguous")])
def test_uncertain_mutation_is_not_replayed_or_classified_as_stale(monkeypatch, client, failure):
    transport = attach_transport(monkeypatch, client, [failure])
    with pytest.raises(AudiaGenticError, match="NET-AGSV-002"):
        client.cancel_execution_request(Path("/private"), "req")
    assert transport.call_count == 1
    assert client._lease_id == "old-lease"


def test_cached_catalog_read_uses_canonical_readonly_reattach(monkeypatch, client):
    from audiagentic.components.agents.gateway.client import _READ_ONLY_GATEWAY_METHODS

    assert "list_agent_definition_cards" in _READ_ONLY_GATEWAY_METHODS
    assert "recover_execution_request" not in _READ_ONLY_GATEWAY_METHODS
    cards = [{"agent_id": "reviewer", "name": "Reviewer"}]
    transport = attach_transport(monkeypatch, client, [stale(), health(), Response({"lease-id": "new-lease", "owner-epoch": "new-epoch"}), Response(cards)])
    assert client.list_agent_definition_cards(Path("/private")) == cards
    assert paths(transport) == ["/shared/v1/call", "/shared/v1/health", "/shared/v1/client-leases/acquire", "/shared/v1/call"]
    assert client._owner_epoch == "new-epoch"
