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


@pytest.mark.parametrize("kind", ["queued-unclaimed", "running-unbound", "authorized", "terminal-receipt"])
def test_host_startup_defers_node_work_without_interrupting_or_local_dispatch(tmp_path, monkeypatch, kind):
    from unittest.mock import Mock

    from tests.unit.agents.test_gateway_node_recovery import make_record

    from audiagentic.components.agents.gateway import api, store
    from audiagentic.components.agents.gateway.queue import recovery, work_index
    from audiagentic.components.providers import providers_api
    from audiagentic.runtime.bootstrap import gateway_service_composition as composition

    monkeypatch.setattr(composition, "build_gateway_service_graph", lambda: SimpleNamespace(shutdown=lambda: None))
    config = _config(tmp_path)
    host = GatewayServiceHost.create(shared_config=config, application=object())
    root = config.projects["project"]
    before = make_record(root, host.service_store, kind, cancel=True)
    ordinary = store.build_record(execution_profile_id="ordinary", prompt_body="ordinary work")
    store.write_record(root, ordinary)
    work_index.write_work_index_entry(host.service_store.root, root, ordinary["request-id"], phase="admitted")
    queue = Mock()
    monkeypatch.setattr(api, "get_queue_manager", lambda: queue)
    routed = []
    def ordinary_runner(record, **kwargs):
        assert record.get("node-placement") is None, "Node work reached ordinary recovery"
        routed.append(record["request-id"])
        return lambda *args, **kwargs: record
    monkeypatch.setattr(recovery, "recovery_runner", ordinary_runner)
    monkeypatch.setattr(providers_api, "validate_gpt_auto_configuration", lambda *args: None)
    from audiagentic.components.agents.gateway.service import known_projects
    monkeypatch.setattr(known_projects, "scan_known_gpt_auto_projects", lambda *args, **kwargs: None)
    for name in ("_start_ingress_poller", "_start_operations_poller", "_stop_background"):
        monkeypatch.setattr(host, name, lambda: None)
    monkeypatch.setattr(host.lifecycle, "start", lambda: None)
    served = []
    monkeypatch.setattr(host.server, "serve_forever", lambda **kwargs: served.append(True))
    try:
        host.serve_forever()
        current = store.read_record(root, before["request-id"])
        assert served == [True]
        assert routed == [ordinary["request-id"]]
        assert current["state"] == before["state"]
        for key in ("worker-id", "attempt-epoch", "node-dispatch", "cancel-requested"):
            assert current[key] == before[key]
        assert current["recovery"]["phase"] == "node-runtime-unavailable"
        assert current["recovery"]["next-retry-at"] is None
        assert current["watchdog-reason"] == "node-runtime-unavailable"
        assert current["watchdog-state"] == ("not-started" if kind == "queued-unclaimed" else "intervention")
        assert queue.enqueue_recovered_queued.call_count == 1
        queue.enqueue_recovered_running.assert_not_called()
    finally:
        host.close()
