"""Node grant composition uses the existing standalone host operation pump."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
import yaml

from audiagentic.components.agents.gateway.operations import (
    ManagementCommand,
    ManagementOperationKind,
    ManagementOperationStore,
)
from audiagentic.components.agents.gateway.service.host import GatewayServiceHost
from audiagentic.components.agents.gateway.service.shared_config import load_shared_server_config
from audiagentic.foundation.contracts.errors import AudiaGenticError


def _config(tmp_path, *, duplicate_token=False):
    for name in ("project", "state"):
        (tmp_path / name).mkdir()
    for name, text in (("principal", "principal-credential"),
                       ("node", "principal-credential" if duplicate_token else "node-credential")):
        token = tmp_path / f"{name}.token"
        token.write_text(text, encoding="utf-8")
        token.chmod(0o600)
    path = tmp_path / "server.yaml"
    path.write_text(yaml.safe_dump({
        "schema-version": 1, "server-id": "server", "listen": {"port": 0},
        "service-root": "state", "projects": {"project": "project"},
        "principals": {"alice": {"token-file": "principal.token", "projects": ["project"],
                                 "actions": ["read", "submit"]}},
        "node-listen": {"port": 0},
        "nodes": {"node": {"token-file": "node.token", "workspaces": {"workspace": "project"},
                           "principals": ["alice"], "revision": 1, "enabled": True}},
    }), encoding="utf-8")
    return load_shared_server_config(path)


def test_host_uses_one_authority_and_existing_pump_for_durable_revoke(tmp_path, monkeypatch):
    from audiagentic.runtime.bootstrap import gateway_service_composition as composition

    shutdowns = []
    monkeypatch.setattr(composition, "build_gateway_service_graph",
                        lambda: SimpleNamespace(shutdown=lambda: shutdowns.append(True)))
    config = _config(tmp_path)
    host = GatewayServiceHost.create(shared_config=config, application=object())
    try:
        assert host._node_authority is not None
        assert host._node_authority.service_root == host.service_store.root
        operations = ManagementOperationStore(host.service_store.root)
        operations.create(ManagementCommand(
            "op-node-revoke", ManagementOperationKind.NODE_REVOKE,
            {"node-id": "node", "expected-grant-revision": 1},
        ), local_only=True)
        monkeypatch.setattr(host, "run_watchdog_pass", lambda: ())
        # Startup scan runs synchronously; no notification or separate queue.
        host._start_operations_poller(interval_seconds=60)
        result = operations.read("op-node-revoke")
        assert result["state"] == "completed"
        grant = load_shared_server_config(config.config_path).nodes[0]
        assert grant.revision == 2 and grant.enabled is False
    finally:
        host.close()
    assert shutdowns == [True]


def test_host_refuses_equal_human_and_node_tokens_before_claim(tmp_path, monkeypatch):
    from audiagentic.runtime.bootstrap import gateway_service_composition as composition

    shutdowns = []
    monkeypatch.setattr(composition, "build_gateway_service_graph",
                        lambda: SimpleNamespace(shutdown=lambda: shutdowns.append(True)))
    config = _config(tmp_path, duplicate_token=True)
    with pytest.raises(AudiaGenticError, match="VAL-AGND-001"):
        GatewayServiceHost.create(shared_config=config, application=object())
    assert shutdowns == [True]
