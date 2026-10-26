"""Local node operator keywords queue intent without starting gateway runtime."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from audiagentic.commands import gateway
from audiagentic.components.agents.gateway.operations import (
    GatewayOperationExecutor,
    ManagementCommand,
    ManagementOperationKind,
    ManagementOperationPump,
    ManagementOperationStore,
)
from audiagentic.components.agents.gateway.service.host import (
    GATEWAY_SERVICE_KEY,
    GatewayServiceHost,
)
from audiagentic.foundation.system.managed_service import ManagedServiceStore
from audiagentic.launcher import main


@pytest.fixture
def configured(tmp_path, monkeypatch):
    base = tmp_path / "service-base"
    base.mkdir()
    project = tmp_path / "project"
    project.mkdir()
    token = tmp_path / "principal.token"
    token.write_text("private-principal-token")
    token.chmod(0o600)
    config = tmp_path / "server.yaml"
    config.write_text('''schema-version: 1
server-id: local-test
listen:
  host: 127.0.0.1
  port: 9011
service-root: service-base
projects:
  project: project
principals:
  operator:
    token-file: principal.token
    projects: [project]
    actions: [read]
''')
    start = Mock(side_effect=AssertionError("service startup is forbidden"))
    monkeypatch.setattr(GatewayServiceHost, "create", start)
    network = Mock(side_effect=AssertionError("network client is forbidden"))
    monkeypatch.setattr(gateway, "_shared_client", network)
    service = ManagedServiceStore(GATEWAY_SERVICE_KEY, root=base)
    store = ManagementOperationStore(service.root)
    return config, service, store, start, network


def revoke(config, node="build-node", revision="7"):
    return ["gateway", "node", "revoke", "config", str(config), "node", node, "revision", revision]


def status(config, operation):
    return ["gateway", "node", "revoke", "status", "config", str(config), "operation", operation, "output", "json"]


@pytest.mark.parametrize("tokens", [["node"], ["node", "help"], ["node", "revoke", "help"], ["node", "revoke", "status", "help"]])
def test_node_help_is_pure_in_fresh_process(tokens):
    script = '''
import importlib.abc
import sys
class Guard(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(("audiagentic.runtime", "audiagentic.components", "audiagentic.commands.bootstrap", "playwright", "selenium")):
            raise AssertionError("startup import: " + fullname)
sys.meta_path.insert(0, Guard())
from audiagentic.launcher import main
raise SystemExit(main(["gateway", *sys.argv[1:]]))
'''
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[3] / "src"))
    result = subprocess.run([sys.executable, "-c", script, *tokens], env=env, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert not result.stderr
    assert "revision N" in result.stdout and "output json" in result.stdout
    assert "accepted means queued" in result.stdout
    assert "Examples:" in result.stdout


def test_root_help_advertises_node_commands(capsys):
    assert main(["gateway", "help"]) == 0
    assert "gateway node revoke" in capsys.readouterr().out


@pytest.mark.parametrize("tokens", [
    ["revoke"], ["status"], ["revoke", "--config", "server.yaml"],
    ["revoke", "config", "x", "node", "n", "revision"],
    ["revoke", "config", "x", "node", "n", "revision", "7", "extra"],
    ["revoke", "config", "x", "node", "n", "revision", "+7"],
    ["revoke", "config", "x", "node", "n", "revision", "7.0"],
    ["revoke", "config", "x", "node", "n", "revision", "٧"],
    ["revoke", "config", "x", "node", "n", "revision", "9" * 5000],
    ["revoke", "status", "config", "x", "operation", "op-valid"],
    ["revoke", "status", "config", "x", "operation", "op-valid", "output", "text"],
    ["revoke", "status", "config", "x", "operation", "op-valid", "output", "json", "extra"],
    ["revoke", "config", "x", "revision", "7", "node", "n"],
    ["revoke", "config", "--private-token", "node", "n", "revision", "7"],
])
def test_node_grammar_rejected_before_config_or_filesystem(tokens, monkeypatch, capsys):
    from audiagentic.components.agents.gateway.service import shared_config
    loader = Mock(side_effect=AssertionError("configuration must not be loaded"))
    monkeypatch.setattr(shared_config, "load_shared_server_config", loader)
    assert main(["gateway", "node", *tokens]) == 2
    output = capsys.readouterr()
    assert "gateway node help" in output.err
    assert "--private-token" not in output.err
    loader.assert_not_called()


def test_revoke_queues_exact_local_command_and_status_is_redacted_read(configured, monkeypatch, capsys):
    config, service, store, start, network = configured
    original = ManagementOperationStore.create
    commands = []
    def create(self, command, *, local_only=False):
        commands.append((command, local_only))
        return original(self, command, local_only=local_only)
    monkeypatch.setattr(ManagementOperationStore, "create", create)
    assert main(revoke(config)) == 0
    receipt = json.loads(capsys.readouterr().out)
    operation = receipt["operation-id"]
    assert receipt["kind"] == "node-revoke" and receipt["state"] == "accepted"
    assert commands[0][0].kind is ManagementOperationKind.NODE_REVOKE
    assert commands[0][0].scope == {"node-id": "build-node", "expected-grant-revision": 7}
    assert commands[0][1] is True
    record_path = store.root / operation / "record.json"
    timeline = store.root / operation / "timeline.ndjson"
    before = record_path.read_bytes(), timeline.read_bytes()
    assert not service.record_path.exists()
    assert main(status(config, operation)) == 0
    output = capsys.readouterr()
    assert json.loads(output.out) == receipt
    assert (record_path.read_bytes(), timeline.read_bytes()) == before
    assert len(commands) == 1
    for hidden in ("scope", "intent-digest", "owner-epoch", "private-principal-token", str(config), str(service.root)):
        assert hidden not in output.out
    start.assert_not_called()
    network.assert_not_called()


def test_default_service_root_is_resolved_by_managed_store(configured, tmp_path, monkeypatch, capsys):
    from audiagentic.foundation.system import managed_service
    config, _, _, _, _ = configured
    config.write_text(config.read_text().replace("service-root: service-base\n", ""))
    monkeypatch.setattr(managed_service, "global_service_runtime", lambda: tmp_path / "default-runtime")
    assert main(revoke(config)) == 0
    operation = json.loads(capsys.readouterr().out)["operation-id"]
    canonical = ManagementOperationStore(ManagedServiceStore(GATEWAY_SERVICE_KEY).root)
    assert canonical.read(operation)["state"] == "accepted"
    assert not (tmp_path / "gateway-operations").exists()


@pytest.mark.parametrize("node,revision", [("../node", "7"), ("", "7"), ("node", "0"), ("node", "-1"), ("node", str(2**63))])
def test_scope_validation_cannot_queue_invalid_intent(configured, node, revision, capsys):
    config, _, store, _, _ = configured
    assert main(revoke(config, node, revision)) in {1, 2}
    assert not list(store.root.glob("*/record.json"))
    assert capsys.readouterr().err


def test_status_missing_wrong_kind_and_invalid_id_fail_without_execution(configured, capsys):
    config, _, store, _, _ = configured
    for operation in ("op-missing", "../invalid"):
        assert main(status(config, operation)) == 1
        assert capsys.readouterr().err
    other = store.create(ManagementCommand("op-other", ManagementOperationKind.RECONCILE, {}))
    assert main(status(config, other["operation-id"])) == 1
    assert "not a node-revoke" in capsys.readouterr().err
    assert store.read("op-other")["state"] == "accepted"


def test_existing_pump_alone_executes_revocation_and_status_reports_completion(configured, capsys):
    config, _, store, start, network = configured
    assert main(revoke(config)) == 0
    operation = json.loads(capsys.readouterr().out)["operation-id"]
    authority = Mock()
    authority.revoke.return_value = {"token": "private", "native-ref": "private"}
    effects = GatewayOperationExecutor(Mock(), node_authority=authority)
    finished = ManagementOperationPump(store, effects).run_once(owner_epoch="operator-owner")
    assert finished[0]["state"] == "completed"
    assert main(status(config, operation)) == 0
    output = capsys.readouterr().out
    assert json.loads(output)["result"] == {"node-id": "build-node", "revoked": True}
    assert "private" not in output and "operator-owner" not in output
    authority.revoke.assert_called_once_with("build-node", expected_grant_revision=7)
    start.assert_not_called()
    network.assert_not_called()


def test_invalid_config_uses_registered_error_and_does_not_create_queue(configured, capsys):
    config, _, store, _, _ = configured
    config.write_text("schema-version: 999\nsecret: private-principal-token\n")
    assert main(revoke(config)) == 1
    output = capsys.readouterr()
    assert "VAL-AGSV-006" in output.err
    assert "private-principal-token" not in output.err
    assert not store.root.exists()


def test_status_reports_pump_failure_without_exception_details(configured, capsys):
    config, _, store, _, _ = configured
    assert main(revoke(config)) == 0
    operation = json.loads(capsys.readouterr().out)["operation-id"]
    store.claim(operation, owner_epoch="private-owner")
    store.fail(operation, owner_epoch="private-owner", code="CON-AGND-001")
    assert main(status(config, operation)) == 0
    output = capsys.readouterr().out
    result = json.loads(output)
    assert result["state"] == "failed"
    assert result["error"] == {"code": "CON-AGND-001"}
    assert "private-owner" not in output
