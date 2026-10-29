"""SH38 private config contracts, independent of transport and writers."""
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest
import yaml

from audiagentic.components.agents.gateway.service.shared_config import (
    SharedGatewayServerConfig,
    load_shared_node_config,
    load_shared_server_config,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError


@pytest.fixture
def configs(tmp_path):
    for name in ("project", "state"):
        (tmp_path / name).mkdir()
    for name in ("principal.token", "node.token", "other.token"):
        token = tmp_path / name
        token.write_text("same-bytes-startup-owner-checks", encoding="utf-8")
        token.chmod(0o600)
    server = {
        "schema-version": 1, "server-id": "server", "listen": {"port": 8000},
        "projects": {"project": "project"},
        "principals": {"alice": {"token-file": "principal.token", "projects": ["project"], "actions": ["read"]}},
        "node-listen": {"port": 8001},
        "nodes": {"node": {"token-file": "node.token", "workspaces": {"workspace": "project"},
                           "principals": ["alice"], "revision": 1, "enabled": True}},
    }
    node = {
        "schema-version": 1, "node-id": "node", "server-id": "server",
        "endpoint": "wss://gateway.example/shared/v1/nodes/connect", "token-file": "node.token",
        "state-root": "state", "workspaces": {"workspace": {"root": "project", "execution-profiles": ["default"]}},
    }
    return tmp_path, server, node


def load(base, value, loader):
    path = base / "config.yaml"
    path.write_text(yaml.safe_dump(value), encoding="utf-8")
    return loader(path)


def test_stage1_construction_and_load_defaults(configs):
    base, server, _ = configs
    del server["nodes"], server["node-listen"]
    result = load(base, server, load_shared_server_config)
    assert result.nodes == () and result.node_listen is None
    assert result.config_path == (base / "config.yaml").resolve()
    assert "config_path" not in repr(result)
    constructed = SharedGatewayServerConfig(server_id="server", port=0, service_root=None,
                                           projects={}, principals=())
    assert constructed.config_path is None and constructed.nodes == ()


def test_node_grants_are_scoped_and_frozen(configs):
    base, server, _ = configs
    server["nodes"]["other"] = dict(server["nodes"]["node"], **{"token-file": "other.token"})
    result = load(base, server, load_shared_server_config)
    assert result.node_listen.host == "127.0.0.1" and result.node_listen.port == 8001
    assert len(result.nodes) == 2
    assert result.nodes[0].workspaces == result.nodes[1].workspaces == {"workspace": "project"}
    assert result.nodes[0].principals == frozenset({"alice"})
    with pytest.raises(FrozenInstanceError):
        result.nodes[0].enabled = False


@pytest.mark.parametrize("field,value", [
    ("revision", True), ("revision", 0), ("revision", "1"), ("revision", 1.5),
    ("enabled", 1), ("enabled", "true"), ("principals", ["unknown"]),
    ("principals", ["alice", "alice"]), ("principals", []),
    ("workspaces", {}), ("workspaces", {"workspace": "missing"}),
    ("workspaces", {"workspace": "/foreign/path"}), ("workspaces", {"workspace": {"root": "project"}}),
    ("token-file", "principal.token"), ("unknown", True),
])
def test_invalid_server_node_grants(configs, field, value):
    base, server, _ = configs
    server["nodes"]["node"][field] = value
    with pytest.raises(AudiaGenticError):
        load(base, server, load_shared_server_config)


@pytest.mark.parametrize("listen", [None, {}, {"host": "0.0.0.0", "port": 8001}, {"port": True}, {"port": 8001, "extra": 1}])
def test_nodes_require_valid_loopback_listener(configs, listen):
    base, server, _ = configs
    if listen is None:
        del server["node-listen"]
    else:
        server["node-listen"] = listen
    with pytest.raises(AudiaGenticError):
        load(base, server, load_shared_server_config)


def test_node_credential_hardlink_alias_rejected(configs):
    base, server, _ = configs
    (base / "alias").hardlink_to(base / "node.token")
    server["nodes"]["other"] = dict(server["nodes"]["node"], **{"token-file": "alias"})
    with pytest.raises(AudiaGenticError) as caught:
        load(base, server, load_shared_server_config)
    assert caught.value.code == "VAL-AGSV-011"


def test_node_local_paths_and_no_token_reads(configs, monkeypatch):
    base, _, node = configs
    original = Path.read_text

    def guarded(self, *args, **kwargs):
        assert self.suffix != ".token"
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded)
    result = load(base, node, load_shared_node_config)
    assert result.state_root == (base / "state").resolve()
    assert result.workspaces["workspace"].root == (base / "project").resolve()
    assert result.workspaces["workspace"].execution_profiles == frozenset({"default"})
    assert result.ca_file is None


@pytest.mark.parametrize("endpoint", [
    "https://gateway/shared/v1/nodes/connect", "ws://gateway/shared/v1/nodes/connect",
    "wss://gateway", "wss://gateway/shared/v1/nodes/connect/",
    "wss://user:SECRET@gateway/shared/v1/nodes/connect",
    "wss://gateway/shared/v1/nodes/connect?", "wss://gateway/shared/v1/nodes/connect#",
    "wss://gateway:0/shared/v1/nodes/connect", "wss://gateway:bad/shared/v1/nodes/connect",
])
def test_node_endpoint_is_exact(configs, endpoint):
    base, _, node = configs
    node["endpoint"] = endpoint
    with pytest.raises(AudiaGenticError) as caught:
        load(base, node, load_shared_node_config)
    assert "SECRET" not in str(caught.value)


@pytest.mark.parametrize("workspace", [
    {}, {"root": "missing", "execution-profiles": ["default"]},
    {"root": "node.token", "execution-profiles": ["default"]},
    {"root": "project", "execution-profiles": []},
    {"root": "project", "execution-profiles": [True]},
    {"root": "project", "execution-profiles": ["default", "default"]},
    {"root": "project", "execution-profiles": ["default"], "component-profile": "other"},
])
def test_node_workspace_validation(configs, workspace):
    base, _, node = configs
    node["workspaces"]["workspace"] = workspace
    with pytest.raises(AudiaGenticError):
        load(base, node, load_shared_node_config)


@pytest.mark.parametrize("raw", ["[]", "true", "", "schema-version: 1\nschema-version: 1", "!!python/object:SECRET {}"])
def test_node_yaml_failure_sanitized(configs, raw):
    path = configs[0] / "bad.yaml"
    path.write_text(raw, encoding="utf-8")
    with pytest.raises(AudiaGenticError) as caught:
        load_shared_node_config(path)
    assert caught.value.code == "VAL-AGSV-006"
    assert "SECRET" not in str(caught.value)


@pytest.mark.parametrize("field,value", [
    ("node-id", "../node"), ("server-id", True), ("schema-version", True),
    ("state-root", "missing"), ("state-root", "node.token"),
    ("token-file", "missing"), ("ca-file", "missing"), ("ca-file", "state"),
    ("workspaces", {}), ("component-profile", "other"),
])
def test_node_top_level_validation(configs, field, value):
    base, _, node = configs
    node[field] = value
    with pytest.raises(AudiaGenticError):
        load(base, node, load_shared_node_config)


def test_disabled_node_and_optional_ca(configs):
    base, server, node = configs
    server["nodes"]["node"]["enabled"] = False
    assert load(base, server, load_shared_server_config).nodes[0].enabled is False
    (base / "ca.pem").write_text("startup-validates-certificate", encoding="utf-8")
    node["ca-file"] = "ca.pem"
    assert load(base, node, load_shared_node_config).ca_file == (base / "ca.pem").resolve()
