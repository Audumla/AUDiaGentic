"""Local connector supplies caller context and source credentials, never the model."""
import json
from unittest.mock import Mock

import pytest
import yaml

from audiagentic.components.agents.gateway.remote_client import StandaloneGatewayClient
from audiagentic.components.agents.gateway.service.contract import HEALTH_ROUTE
from audiagentic.components.agents.gateway.service.shared_config import load_shared_connector_config
from audiagentic.foundation.contracts.errors import AudiaGenticError

from .test_gateway_shared_remote_client import Response


@pytest.fixture
def configured(tmp_path, monkeypatch):
    for name in ("project", "other", "state"):
        (tmp_path / name).mkdir()
    for name, value in (("node-token", "private-node-credential"), ("principal-token", "private-principal-credential")):
        path = tmp_path / name
        path.write_text(value)
        path.chmod(0o600)
    node = {
        "schema-version": 1, "node-id": "caller-node", "server-id": "server-a",
        "endpoint": "wss://gateway.example:9443/shared/v1/nodes/connect",
        "token-file": "node-token", "state-root": "state",
        "workspaces": {"caller-workspace": {"root": "project", "execution-profiles": ["profile"]},
                       "other-workspace": {"root": "other", "execution-profiles": ["profile"]}},
    }
    path = tmp_path / "node.yaml"
    path.write_text(yaml.safe_dump(node))
    client = StandaloneGatewayClient(
        "https://gateway.example:9443", "private-principal-credential",
        shared_server_id="server-a", shared_project_id="project-a",
        shared_source_node_config=path, shared_caller_root=tmp_path / "project",
    )
    client._lease_id, client._owner_epoch = "lease", "owner"
    monkeypatch.setattr(client, "_ensure_lease", Mock())
    requests = []
    def opened(request, **kwargs):
        requests.append(request)
        return Response({"state": "queued"})
    monkeypatch.setattr(client._shared_opener, "open", opened)
    return client, tmp_path, path, node, requests


def test_private_source_context_is_derived_and_credential_is_header_only(configured):
    client, root, _, _, requests = configured
    result = client.submit_execution_request(root / "project", agent_id="agent", prompt_body="hello")
    request = requests[0]
    payload = json.loads(request.data)
    assert payload["params"]["node_id"] == "caller-node"
    assert payload["params"]["workspace_id"] == "caller-workspace"
    source = payload["params"]["source_workspace"]
    assert source["caller-root"] == str((root / "project").resolve())
    assert source["identity"]["source-node-id"] == "caller-node"
    assert request.get_header("X-audiagentic-source-node-token") == "private-node-credential"
    assert request.get_header("Authorization") == "Bearer private-principal-credential"
    assert "private-node-credential" not in request.data.decode()
    assert str(root) not in json.dumps(result)
    assert sum(name.lower() == "x-audiagentic-source-node-token" for name, _ in request.header_items()) == 1


@pytest.mark.parametrize("kwargs", [
    {"source_workspace": {}}, {"node_id": "caller-node"},
    {"workspace_id": "caller-workspace"},
    {"node_id": "other-node", "workspace_id": "caller-workspace"},
    {"node_id": "caller-node", "workspace_id": "other-workspace"},
])
def test_model_cannot_inject_source_or_select_another_write_target(configured, kwargs):
    client, root, _, _, requests = configured
    with pytest.raises(AudiaGenticError):
        client.submit_execution_request(root / "project", agent_id="agent", prompt_body="hello", **kwargs)
    assert requests == []
    client._ensure_lease.assert_not_called()


def test_caller_root_and_binding_are_revalidated_without_silent_switch(configured):
    client, root, path, node, requests = configured
    with pytest.raises(AudiaGenticError, match="binding changed"):
        client.submit_execution_request(root / "other", prompt_body="hello")
    node["workspaces"]["caller-workspace"]["execution-profiles"] = ["different-profile"]
    path.write_text(yaml.safe_dump(node))
    with pytest.raises(AudiaGenticError, match="binding changed"):
        client.submit_execution_request(root / "project", prompt_body="hello")
    assert requests == []


def test_node_token_rotation_is_used_without_changing_workspace(configured):
    client, root, _, _, requests = configured
    (root / "node-token").write_text("rotated-private-node-credential")
    client.submit_execution_request(root / "project", prompt_body="hello")
    assert requests[0].get_header("X-audiagentic-source-node-token") == "rotated-private-node-credential"


def test_source_credentials_are_never_sent_on_reads_or_health(configured):
    client, root, _, _, requests = configured
    client.get_execution_request(root / "project", "req_example_retained")
    assert requests[0].get_header("X-audiagentic-source-node-token") is None
    with pytest.raises(AudiaGenticError):
        client._request(HEALTH_ROUTE, None, method="GET", source_node_token="private-node-credential")
    assert len(requests) == 1


def test_no_enrollment_means_explicit_node_target_cannot_fall_back(monkeypatch, tmp_path):
    client = StandaloneGatewayClient("https://gateway.example", "principal",
                                     shared_server_id="server-a", shared_project_id="project-a")
    ensure = Mock()
    monkeypatch.setattr(client, "_ensure_lease", ensure)
    with pytest.raises(AudiaGenticError, match="enrollment"):
        client.submit_execution_request(tmp_path, node_id="node", workspace_id="workspace", prompt_body="hello")
    ensure.assert_not_called()


def test_connector_config_references_local_node_config_instead_of_recipient_defaults(configured):
    _, root, node_path, _, _ = configured
    connector = {
        "schema-version": 1, "mode": "shared", "server-id": "server-a",
        "endpoint": "https://gateway.example", "token-file": "principal-token",
        "source-node-config": "node.yaml",
    }
    path = root / "connector.yaml"
    path.write_text(yaml.safe_dump(connector))
    loaded = load_shared_connector_config(path)
    assert loaded.source_node_config_file == node_path
    assert str(node_path) not in repr(loaded)
    connector.update({"node-id": "node", "workspace-id": "workspace"})
    path.write_text(yaml.safe_dump(connector))
    with pytest.raises(AudiaGenticError):
        load_shared_connector_config(path)
