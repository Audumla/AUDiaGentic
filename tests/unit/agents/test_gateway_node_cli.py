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


@pytest.mark.parametrize("tokens", [["node", "serve", "help"], ["node", "help"], ["help"]])
def test_node_serve_help_is_cold_and_lists_exact_keyword(tokens):
    script = '''
import importlib.abc
import sys
class Guard(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(("audiagentic.runtime", "audiagentic.components", "websockets", "playwright")):
            raise AssertionError("cold import: " + fullname)
sys.meta_path.insert(0, Guard())
from audiagentic.launcher import main
raise SystemExit(main(["gateway", *sys.argv[1:]]))
'''
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[3] / "src"))
    result = subprocess.run([sys.executable, "-c", script, *tokens], env=env, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert "gateway node serve config FILE" in result.stdout
    assert not result.stderr


@pytest.mark.parametrize("tail", [[], ["config"], ["--config", "x"], ["config", "x", "extra"],
    ["config", "--private"], ["help", "extra"], ["config", "x", "--force"]])
def test_node_serve_grammar_rejected_before_owner_imports(tail):
    script = '''
import importlib.abc
import sys
class Guard(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(("audiagentic.runtime", "audiagentic.components", "websockets")):
            raise AssertionError("startup import: " + fullname)
sys.meta_path.insert(0, Guard())
from audiagentic.launcher import main
raise SystemExit(main(["gateway", "node", "serve", *sys.argv[1:]]))
'''
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[3] / "src"))
    result = subprocess.run([sys.executable, "-c", script, *tail], env=env, capture_output=True, text=True, timeout=15)
    assert result.returncode == 2
    assert "node serve help" in result.stderr and "private" not in result.stderr


@pytest.fixture
def node_serve_config(tmp_path):
    (tmp_path / "state").mkdir()
    (tmp_path / "workspace").mkdir()
    token = tmp_path / "node.token"
    token.write_text("private-node-token")
    token.chmod(0o600)
    path = tmp_path / "node.yaml"
    path.write_text('''schema-version: 1
node-id: build-node
server-id: local-test
endpoint: wss://localhost/shared/v1/nodes/connect
token-file: node.token
state-root: state
workspaces:
  checkout:
    root: workspace
    execution-profiles: [profile]
''')
    return path


@pytest.mark.parametrize("disposition,expected", [("stopped", 0), ("retry-exhausted", 1), ("deferred", 1)])
def test_node_serve_entrypoint_outcome_and_stop_only_signal_restoration(node_serve_config, monkeypatch, capsys, disposition, expected):
    from types import SimpleNamespace

    from audiagentic.components.agents.gateway.node.host import (
        NodeRecipientHost,
        NodeRecipientOutcome,
    )
    from audiagentic.foundation.contracts.errors import AudiaGenticError
    from audiagentic.runtime import component_context
    handlers, installs = {}, []
    originals = {sig: object() for sig in gateway._shutdown_signals()}
    monkeypatch.setattr(gateway.signal, "getsignal", lambda sig: originals[sig])
    def install(sig, handler):
        handlers[sig] = handler
        installs.append((sig, handler))
    monkeypatch.setattr(gateway.signal, "signal", install)
    stop = Mock()
    async def run():
        for sig in originals:
            handlers[sig](sig, None)
        cause = None if disposition == "stopped" else AudiaGenticError(
            code="CON-AGND-001", kind="agents", message="receipt ack timeout",
            details={"stage": "observe", "reason-code": "receipt-ack-timeout"},
        )
        return NodeRecipientOutcome(disposition, cause)
    host = SimpleNamespace(run=run, request_stop=stop, failure={"code": "historic"})
    def create(config, *, component_context_reader):
        assert config.node_id == "build-node" and config.server_id == "local-test"
        assert component_context_reader is component_context.collect_component_context
        return host
    monkeypatch.setattr(NodeRecipientHost, "create", create)
    assert main(["gateway", "node", "serve", "config", str(node_serve_config)]) == expected
    assert stop.call_count == len(originals)
    assert all(handlers[sig] is original for sig, original in originals.items())
    assert len(installs) == 2 * len(originals)
    output = capsys.readouterr()
    assert "private-node-token" not in output.out + output.err
    if expected:
        assert disposition in output.err


@pytest.mark.parametrize("installed", [None, "14.2", "16.0"])
def test_node_serve_missing_pinned_dependency_is_actionable(node_serve_config, monkeypatch, capsys, installed):
    from types import SimpleNamespace
    monkeypatch.setitem(sys.modules, "websockets", None if installed is None else SimpleNamespace(__version__=installed))
    assert main(["gateway", "node", "serve", "config", str(node_serve_config)]) == 1
    error = capsys.readouterr().err
    assert "VAL-AGND-001" in error and "audiagentic[node]" in error and "websockets>=15,<16" in error


def test_node_serve_server_configuration_is_rejected_by_node_loader(configured, monkeypatch):
    from audiagentic.components.agents.gateway.service import shared_config
    server_config = configured[0]
    forbidden = Mock(side_effect=AssertionError("serve must never load SERVER configuration"))
    monkeypatch.setattr(shared_config, "load_shared_server_config", forbidden)
    assert main(["gateway", "node", "serve", "config", str(server_config)]) == 1
    forbidden.assert_not_called()


def test_node_revoke_still_rejects_node_configuration(node_serve_config):
    assert main(revoke(node_serve_config)) == 1


def test_node_serve_real_claim_stop_without_transport(node_serve_config, monkeypatch):
    from audiagentic.components.agents.gateway.node.host import NodeRecipientHost
    from audiagentic.components.agents.gateway.node.transport import NodeTransportClient
    hosts = []
    original = NodeRecipientHost.create
    def create(*args, **kwargs):
        host = original(*args, **kwargs)
        hosts.append(host)
        return host
    monkeypatch.setattr(NodeRecipientHost, "create", create)
    monkeypatch.setattr(NodeTransportClient, "connect", Mock(side_effect=AssertionError("no native/transport start")))
    monkeypatch.setattr(gateway.signal, "getsignal", lambda sig: None)
    def install(sig, handler):
        if callable(handler):
            assert hosts[0].service_store.read().state == "running"
            handler(sig, None)
    monkeypatch.setattr(gateway.signal, "signal", install)
    assert main(["gateway", "node", "serve", "config", str(node_serve_config)]) == 0
    assert hosts[0].service_store.read().state == "stopped"
