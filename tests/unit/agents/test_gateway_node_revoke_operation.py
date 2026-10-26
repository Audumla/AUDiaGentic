"""Local node revocation uses the existing durable operation store and pump."""
import json
from copy import deepcopy
from unittest.mock import Mock

import pytest

from audiagentic.components.agents.gateway.operations import (
    GatewayOperationExecutor,
    GatewayOperationsApplication,
    ManagementCommand,
    ManagementOperationKind,
    ManagementOperationPump,
    ManagementOperationStore,
)
from audiagentic.components.agents.gateway.service.application import GatewayServiceApplication
from audiagentic.foundation.contracts.errors import AudiaGenticError


def command(operation_id="op-node-revoke", **scope):
    return ManagementCommand(
        operation_id=operation_id, kind=ManagementOperationKind.NODE_REVOKE,
        scope={"node-id": "node-1", "expected-grant-revision": 7, **scope},
    )


def executor(authority=None):
    # Native/provider/application paths must not be used for a local revoke.
    app = Mock()
    return GatewayOperationExecutor(app, node_authority=authority), app


def test_local_revoke_uses_existing_store_and_pump_once(tmp_path):
    operation_store = ManagementOperationStore(tmp_path)
    created = operation_store.create(command(), local_only=True)
    assert operation_store.create(command(), local_only=True) == created
    authority = Mock()
    authority.revoke.return_value = {"credentials": "private", "native-ref": "private"}
    effects, application = executor(authority)
    completed = ManagementOperationPump(operation_store, effects).run_once(owner_epoch="owner")
    assert completed[0]["state"] == "completed"
    assert completed[0]["result"] == {"node-id": "node-1", "revoked": True}
    authority.revoke.assert_called_once_with("node-1", expected_grant_revision=7)
    assert application.mock_calls == []
    assert ManagementOperationPump(operation_store, effects).run_once(owner_epoch="next-owner") == []
    assert authority.revoke.call_count == 1
    assert operation_store.read(created["operation-id"]) == completed[0]
    persisted = (operation_store.root / created["operation-id"] / "record.json").read_text()
    assert "private" not in persisted
    assert "local_only" not in persisted


@pytest.mark.parametrize("invalid", [
    {}, {"node-id": "node-1"}, {"expected-grant-revision": 7},
    {"node-id": "../node", "expected-grant-revision": 7},
    {"node-id": "", "expected-grant-revision": 7},
    {"node-id": "node-1", "expected-grant-revision": True},
    {"node-id": "node-1", "expected-grant-revision": 0},
    {"node-id": "node-1", "expected-grant-revision": -1},
    {"node-id": "node-1", "expected-grant-revision": 2**63},
    {"node-id": "node-1", "expected-grant-revision": "7"},
    {"node-id": "node-1", "expected-grant-revision": 7, "project-root": "/client"},
    {"node-id": "node-1", "expected-grant-revision": 7, "token": "private"},
    {"node_id": "node-1", "expected_grant_revision": 7},
])
def test_strict_scope_fails_before_persistence_or_authority(tmp_path, invalid):
    operation_store = ManagementOperationStore(tmp_path)
    malformed = ManagementCommand("op-invalid", ManagementOperationKind.NODE_REVOKE, invalid)
    with pytest.raises(AudiaGenticError, match="VAL-AGM-004"):
        operation_store.create(malformed, local_only=True)
    assert not operation_store.root.exists()
    authority = Mock()
    effects, _ = executor(authority)
    with pytest.raises(AudiaGenticError, match="VAL-AGM-004"):
        effects.execute({"kind": "node-revoke", "scope": invalid})
    authority.revoke.assert_not_called()


def test_revoke_command_id_collision_does_not_replace_intent(tmp_path):
    operation_store = ManagementOperationStore(tmp_path)
    created = operation_store.create(command(), local_only=True)
    with pytest.raises(AudiaGenticError, match="CON-AGM-001"):
        operation_store.create(command(**{"expected-grant-revision": 8}), local_only=True)
    assert operation_store.read(created["operation-id"]) == created


def test_disabled_authority_fails_explicitly_and_pump_records_failure(tmp_path):
    operation_store = ManagementOperationStore(tmp_path)
    created = operation_store.create(command(), local_only=True)
    effects, application = executor()
    with pytest.raises(AudiaGenticError, match="UNS-AGM-001"):
        effects.execute(created)
    completed = ManagementOperationPump(operation_store, effects).run_once(owner_epoch="owner")
    assert completed[0]["state"] == "failed"
    # Existing pump deliberately redacts all exception details to this code.
    assert completed[0]["error"] == {"code": "INT-AGM-001"}
    assert application.mock_calls == []


def test_revision_conflict_propagates_without_reporting_success(tmp_path):
    operation_store = ManagementOperationStore(tmp_path)
    created = operation_store.create(command(), local_only=True)
    authority = Mock()
    authority.revoke.side_effect = AudiaGenticError(
        "CON-AGND-001", "agents-node", "grant revision changed", {},
    )
    effects, _ = executor(authority)
    with pytest.raises(AudiaGenticError, match="CON-AGND-001"):
        effects.execute(created)
    authority.revoke.assert_called_once_with("node-1", expected_grant_revision=7)


def test_node_revoke_claims_recover_through_existing_owner_fence(tmp_path):
    operation_store = ManagementOperationStore(tmp_path)
    created = operation_store.create(command(), local_only=True)
    operation_store.claim(created["operation-id"], owner_epoch="old-owner")
    authority = Mock()
    effects, _ = executor(authority)
    completed = ManagementOperationPump(operation_store, effects).run_once(owner_epoch="new-owner")
    assert completed[0]["state"] == "completed"
    assert completed[0]["owner-epoch"] == "new-owner"
    authority.revoke.assert_called_once_with("node-1", expected_grant_revision=7)
    with pytest.raises(AudiaGenticError, match="CON-AGM-002"):
        operation_store.finish(created["operation-id"], owner_epoch="old-owner", result={})


def test_node_revoke_requires_explicit_local_creation_not_generic_service_api(tmp_path):
    operation_store = ManagementOperationStore(tmp_path)
    with pytest.raises(AudiaGenticError, match="UNS-AGM-001"):
        operation_store.create(command())
    with pytest.raises(AudiaGenticError, match="UNS-AGM-001"):
        GatewayOperationsApplication(operation_store).create_operation(command())
    # The existing HTTP translation can parse the new enum but cannot
    # opt in to local-only creation, including by injecting an argument.
    service = GatewayServiceApplication.__new__(GatewayServiceApplication)
    service._operations = GatewayOperationsApplication(operation_store)
    arguments = {
        "operation_id": "op-remote", "kind": "node-revoke",
        "scope": {"node-id": "node-1", "expected-grant-revision": 7},
    }
    with pytest.raises(AudiaGenticError, match="UNS-AGM-001"):
        service._create_gateway_operation(arguments)
    with pytest.raises(AudiaGenticError):
        service._create_gateway_operation({**arguments, "local_only": True})
    assert not operation_store.root.exists()


def test_persisted_revoke_scope_is_validated_on_replay(tmp_path):
    operation_store = ManagementOperationStore(tmp_path)
    created = operation_store.create(command(), local_only=True)
    corrupt = deepcopy(created)
    corrupt["scope"]["unexpected"] = "not-an-authorized-selector"
    path = operation_store.root / created["operation-id"] / "record.json"
    path.write_text(json.dumps(corrupt))
    with pytest.raises(AudiaGenticError, match="VAL-AGM-004"):
        operation_store.read(created["operation-id"])


def _revoke_server_files(tmp_path):
    import yaml

    project = tmp_path / "project"
    project.mkdir()
    service_root = tmp_path / "service"
    service_root.mkdir()
    for name in ("principal.token", "node.token"):
        token = tmp_path / name
        token.write_text(f"private-{name}", encoding="utf-8")
        token.chmod(0o600)
    config_path = tmp_path / "server.yaml"
    config_path.write_text(yaml.safe_dump({
        "schema-version": 1, "server-id": "server", "listen": {"port": 8000},
        "node-listen": {"port": 8001}, "service-root": str(service_root),
        "projects": {"project": "project"},
        "principals": {"principal": {
            "token-file": "principal.token", "projects": ["project"], "actions": ["submit"],
        }},
        "nodes": {"node-1": {
            "token-file": "node.token", "workspaces": {"workspace": "project"},
            "principals": ["principal"], "revision": 7, "enabled": True,
        }},
    }), encoding="utf-8")
    return config_path, service_root


def test_real_authority_pump_recovers_after_config_commit_before_finish(tmp_path, monkeypatch):
    from audiagentic.components.agents.gateway.node import authority as authority_module
    from audiagentic.components.agents.gateway.node.authority import NodeGrantAuthority
    from audiagentic.components.agents.gateway.service.shared_config import (
        load_shared_server_config,
    )

    config_path, service_root = _revoke_server_files(tmp_path)
    operation_store = ManagementOperationStore(service_root)
    created = operation_store.create(command(), local_only=True)
    first_authority = NodeGrantAuthority(load_shared_server_config(config_path))
    effects, application = executor(first_authority)

    class SimulatedOwnerCrash(BaseException):
        pass

    committed = {}
    def crash_before_operation_finish(*args, **kwargs):
        grant = load_shared_server_config(config_path).nodes[0]
        assert not grant.enabled
        assert grant.revision == 8
        committed["bytes"] = config_path.read_bytes()
        raise SimulatedOwnerCrash

    # BaseException models a process stopping outside the pump's ordinary
    # exception-to-failure handling. All mutation/authority locks have exited.
    with monkeypatch.context() as crash:
        crash.setattr(operation_store, "finish", crash_before_operation_finish)
        with pytest.raises(SimulatedOwnerCrash):
            ManagementOperationPump(operation_store, effects).run_once(owner_epoch="before-crash")

    interrupted = operation_store.read(created["operation-id"])
    assert interrupted["state"] == "running"
    assert interrupted["owner-epoch"] == "before-crash"
    assert interrupted["result"] is None
    assert application.mock_calls == []

    # Rebuild BOTH authorities from their existing durable owners. The exact
    # already-disabled expected+1 grant is the only acceptable replay result.
    restarted_store = ManagementOperationStore(service_root)
    restarted_authority = NodeGrantAuthority(load_shared_server_config(config_path))
    restarted_effects, restarted_application = executor(restarted_authority)
    unexpected_write = Mock(side_effect=AssertionError("revoke replay must not rewrite server config"))
    monkeypatch.setattr(authority_module, "atomic_write_bytes", unexpected_write)
    completed = ManagementOperationPump(restarted_store, restarted_effects).run_once(owner_epoch="after-crash")
    assert len(completed) == 1
    assert completed[0]["state"] == "completed", completed[0]
    assert completed[0]["owner-epoch"] == "after-crash"
    assert completed[0]["result"] == {"node-id": "node-1", "revoked": True}
    assert config_path.read_bytes() == committed["bytes"]
    grant = load_shared_server_config(config_path).nodes[0]
    assert not grant.enabled and grant.revision == 8
    unexpected_write.assert_not_called()
    assert restarted_application.mock_calls == []
    assert ManagementOperationPump(restarted_store, restarted_effects).run_once(owner_epoch="after-crash") == []


def test_real_authority_pump_recovers_after_child_hard_kill(tmp_path, monkeypatch):
    """Hard process termination after YAML commit, before operation finish."""
    import os
    import subprocess
    import sys
    import time
    from pathlib import Path

    from audiagentic.components.agents.gateway.node import authority as authority_module
    from audiagentic.components.agents.gateway.node.authority import NodeGrantAuthority
    from audiagentic.components.agents.gateway.service.shared_config import (
        load_shared_server_config,
    )

    config_path, service_root = _revoke_server_files(tmp_path)
    operation_store = ManagementOperationStore(service_root)
    created = operation_store.create(command(), local_only=True)
    ready_path = tmp_path / "grant-committed.ready"
    script = r"""
import sys
import threading
from pathlib import Path

from audiagentic.components.agents.gateway.node.authority import NodeGrantAuthority
from audiagentic.components.agents.gateway.operations import (
    GatewayOperationExecutor, ManagementOperationPump, ManagementOperationStore,
)
from audiagentic.components.agents.gateway.service.shared_config import load_shared_server_config

config_path, service_root, ready_path = map(Path, sys.argv[1:])
authority = NodeGrantAuthority(load_shared_server_config(config_path))
operation_store = ManagementOperationStore(service_root)

def pause_before_finish(*args, **kwargs):
    # Executor returned only after the real authority replaced and reloaded
    # the YAML. The operation is still claimed; finish has not written.
    grant = load_shared_server_config(config_path).nodes[0]
    assert grant.enabled is False and grant.revision == 8
    assert operation_store.read(args[0])["state"] == "running"
    ready_path.write_text("grant-committed-before-finish", encoding="utf-8")
    threading.Event().wait(60)
    raise AssertionError("parent did not hard-kill its child")

operation_store.finish = pause_before_finish
executor = GatewayOperationExecutor(object(), node_authority=authority)
ManagementOperationPump(operation_store, executor).run_once(owner_epoch="killed-child-owner")
raise AssertionError("child unexpectedly finished the operation")
"""
    environment = dict(os.environ)
    # Use exactly the package under test, whether source or an installed wheel.
    import_root = str(Path(authority_module.__file__).resolve().parents[5])
    environment["PYTHONPATH"] = os.pathsep.join(filter(None, (
        import_root, environment.get("PYTHONPATH"),
    )))
    child = subprocess.Popen(
        [sys.executable, "-c", script, str(config_path), str(service_root), str(ready_path)],
        cwd=tmp_path, env=environment,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        deadline = time.monotonic() + 30
        while not ready_path.exists():
            if child.poll() is not None:
                stdout, stderr = child.communicate(timeout=5)
                pytest.fail(f"child exited before confirmed grant commit: {child.returncode}; {stdout}; {stderr}")
            if time.monotonic() >= deadline:
                pytest.fail("child did not reach confirmed grant commit before timeout")
            time.sleep(0.02)
        assert child.poll() is None
        committed = config_path.read_bytes()
        grant = load_shared_server_config(config_path).nodes[0]
        assert grant.enabled is False and grant.revision == 8
        interrupted = operation_store.read(created["operation-id"])
        assert interrupted["state"] == "running"
        assert interrupted["owner-epoch"] == "killed-child-owner"
        assert interrupted["result"] is None

        # Popen.kill uses TerminateProcess on Windows and SIGKILL on POSIX.
        # Only this owned child is targeted; no graceful cleanup is invoked.
        child.kill()
        child.communicate(timeout=10)
        assert child.returncode != 0
    finally:
        if child.poll() is None:
            child.kill()
            child.communicate(timeout=10)

    restarted_store = ManagementOperationStore(service_root)
    restarted_authority = NodeGrantAuthority(load_shared_server_config(config_path))
    restarted_effects, application = executor(restarted_authority)
    unexpected_write = Mock(side_effect=AssertionError("hard-kill replay must not rewrite grant config"))
    monkeypatch.setattr(authority_module, "atomic_write_bytes", unexpected_write)
    completed = ManagementOperationPump(restarted_store, restarted_effects).run_once(owner_epoch="restarted-owner")
    assert len(completed) == 1
    assert completed[0]["state"] == "completed", completed[0]
    assert completed[0]["owner-epoch"] == "restarted-owner"
    assert completed[0]["result"] == {"node-id": "node-1", "revoked": True}
    assert completed[0]["revision"] == interrupted["revision"] + 3
    assert config_path.read_bytes() == committed
    grant = load_shared_server_config(config_path).nodes[0]
    assert grant.enabled is False and grant.revision == 8
    unexpected_write.assert_not_called()
    assert application.mock_calls == []
    assert ManagementOperationPump(restarted_store, restarted_effects).run_once(owner_epoch="restarted-owner") == []
