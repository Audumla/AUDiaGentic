"""Historical-only transport eligibility comes exclusively from server-owned facts."""

import hashlib
from dataclasses import replace
from uuid import uuid4

import pytest
import yaml

from audiagentic.components.agents.gateway import store
from audiagentic.components.agents.gateway.node.checkpoints import NodeReceiptCheckpoints
from audiagentic.components.agents.gateway.node.contracts import CommandIdentity, canonical_json
from audiagentic.components.agents.gateway.node.drain import NodeDrainEligibility
from audiagentic.components.agents.gateway.node.preparation import (
    PreparationBinding,
    PromptSemanticIdentity,
    build_final_command_payload,
    prepare_node_command,
)
from audiagentic.components.agents.gateway.service.contract import GATEWAY_SERVICE_KEY
from audiagentic.components.agents.gateway.service.shared_config import load_shared_server_config
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.io import atomic_write_json
from audiagentic.foundation.system.managed_service import ManagedServiceStore


def bound_request(
    root, *, node="node", workspace="workspace", project="project", principal="alice"
):
    record = store.build_record(
        execution_profile_id="profile",
        prompt_body="hello",
        node_placement={
            "node-id": node,
            "workspace-id": workspace,
            "principal-id": principal,
            "server-project-id": project,
            "grant-revision": 1,
        },
    )
    store.write_record(root, record)
    record = store.claim_dispatch(
        root, record["request-id"], owner_epoch="owner", expected_revision=0
    )
    record = store.start_owned_attempt(
        root,
        record["request-id"],
        owner_epoch="owner",
        worker_id="worker",
        expected_revision=record["revision"],
    )
    binding = PreparationBinding(
        "command",
        record["request-id"],
        node,
        "boot",
        "owner",
        1,
        workspace,
        1,
        1,
        "challenge",
        "preparation",
    )
    semantic = PromptSemanticIdentity(
        "a" * 64,
        "b" * 64,
        "prompt",
        "profile",
        1,
        hashlib.sha256(b"expanded").hexdigest(),
        hashlib.sha256(b"hello").hexdigest(),
    )
    prepared = prepare_node_command(
        binding=binding,
        semantic=semantic,
        raw_prompt="hello",
        rendered_prompt="rendered",
        manifest_id="manifest",
        context_fingerprint="c" * 64,
        runtime_digest="d" * 64,
        provider_manifest=b"private",
        worker_id="worker",
        attempt_epoch=1,
        provider_id="provider",
        model_id="model",
        model_alias=None,
    )
    payload = build_final_command_payload(prepared, "hello")
    identity = CommandIdentity(
        "command",
        record["request-id"],
        node,
        "boot",
        "owner",
        1,
        workspace,
        1,
        1,
        hashlib.sha256(canonical_json(payload)).hexdigest(),
        "profile",
    )
    return store.bind_owned_node_dispatch(
        root,
        record["request-id"],
        identity=identity,
        command_payload=payload,
        accepted_attestation=prepared.attestation,
        owner_epoch="owner",
        worker_id="worker",
        attempt_epoch=1,
        expected_revision=record["revision"],
    )


@pytest.fixture
def configured(tmp_path):
    for name in ("project", "state"):
        (tmp_path / name).mkdir()
    for name in ("node", "principal"):
        (tmp_path / name).write_text("token-" + name)
        (tmp_path / name).chmod(0o600)
    data = {
        "schema-version": 1,
        "server-id": "server",
        "listen": {"port": 0},
        "node-listen": {"port": 0},
        "service-root": "state",
        "projects": {"project": "project"},
        "principals": {
            "alice": {"token-file": "principal", "projects": ["project"], "actions": ["submit"]}
        },
        "nodes": {
            "node": {
                "token-file": "node",
                "workspaces": {"workspace": "project"},
                "principals": ["alice"],
                "revision": 2,
                "enabled": False,
            }
        },
    }
    path = tmp_path / "server.yaml"
    path.write_text(yaml.safe_dump(data))
    config = load_shared_server_config(path)
    service = ManagedServiceStore(GATEWAY_SERVICE_KEY, root=config.service_root)
    return config, service, NodeDrainEligibility(config, service)


def test_no_work_is_not_eligible(configured):
    config, _, owner = configured
    assert not owner.eligible(config, config.nodes[0])


def test_canonical_bound_command_is_eligible_without_mutation(configured):
    config, _, owner = configured
    root = config.projects["project"]
    before = bound_request(root)
    assert owner.eligible(config, config.nodes[0])
    assert store.read_record(root, before["request-id"]) == before


@pytest.mark.parametrize(
    "change",
    [{"node": "other"}, {"workspace": "other"}, {"project": "other"}, {"principal": "other"}],
)
def test_wrong_sealed_scope_cannot_establish_eligibility(configured, change):
    config, _, owner = configured
    bound_request(config.projects["project"], **change)
    assert not owner.eligible(config, config.nodes[0])


def test_unbound_admission_and_foreign_root_do_not_count(configured, tmp_path):
    config, _, owner = configured
    ordinary = store.build_record(execution_profile_id="profile", prompt_body="hello")
    store.write_record(config.projects["project"], ordinary)
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    bound_request(foreign)
    assert not owner.eligible(config, config.nodes[0])


def test_valid_prior_custody_is_historical_proof_without_owner_lock(configured, monkeypatch):
    config, service, owner = configured
    checkpoint = NodeReceiptCheckpoints(service, server_id="server", node_id="node")
    atomic_write_json(
        checkpoint.path,
        {
            "version": 1,
            "server-id": "server",
            "node-id": "node",
            "log-incarnation-id": str(uuid4()),
            "sequence": 1,
            "receipt-sha256": "a" * 64,
            "gateway-owner-epoch": "old-owner",
        },
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("auth eligibility inverted managed-service lock order")

    monkeypatch.setattr(service, "_lock", forbidden)
    monkeypatch.setattr(service, "owner_guard", forbidden)
    snapshot = checkpoint.peek()
    assert snapshot.sequence == 1 and snapshot.gateway_owner_epoch == "old-owner"
    assert owner.eligible(config, config.nodes[0])


@pytest.mark.parametrize("mutation", ["server-id", "node-id", "receipt-sha256", "sequence"])
def test_corrupt_or_foreign_custody_fails_closed(configured, mutation):
    config, service, owner = configured
    checkpoint = NodeReceiptCheckpoints(service, server_id="server", node_id="node")
    value = {
        "version": 1,
        "server-id": "server",
        "node-id": "node",
        "log-incarnation-id": str(uuid4()),
        "sequence": 1,
        "receipt-sha256": "a" * 64,
        "gateway-owner-epoch": "owner",
    }
    value[mutation] = 0 if mutation == "sequence" else "wrong"
    atomic_write_json(checkpoint.path, value)
    with pytest.raises(AudiaGenticError):
        owner.eligible(config, config.nodes[0])


def test_eligibility_rejects_other_service_or_changed_server(configured, tmp_path):
    config, _, owner = configured
    with pytest.raises(AudiaGenticError):
        NodeDrainEligibility(
            config, ManagedServiceStore(GATEWAY_SERVICE_KEY, root=tmp_path / "foreign")
        )
    with pytest.raises(AudiaGenticError):
        owner.eligible(replace(config, server_id="other"), config.nodes[0])
    with pytest.raises(AudiaGenticError):
        owner.eligible(replace(config, service_root=tmp_path / "foreign"), config.nodes[0])


def test_node_policy_imports_no_host_composition_root():
    import ast
    from pathlib import Path

    from audiagentic.components.agents.gateway import node

    for path in Path(node.__file__).parent.glob("*.py"):
        for statement in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(statement, ast.ImportFrom):
                module = statement.module or ""
                assert not module.endswith("service.host"), path
                assert not (
                    module.endswith("service")
                    and any(alias.name == "host" for alias in statement.names)
                ), path
            elif isinstance(statement, ast.Import):
                assert not any(alias.name.endswith("service.host") for alias in statement.names), (
                    path
                )


def test_policy_construction_in_fresh_process_never_imports_host(configured):
    import os
    import subprocess
    import sys
    from pathlib import Path

    config, _, _ = configured
    script = """
import importlib.abc
import sys
from pathlib import Path
class Guard(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "audiagentic.components.agents.gateway.service.host":
            raise AssertionError("node policy imported host composition root")
sys.meta_path.insert(0, Guard())
from audiagentic.components.agents.gateway.node.authority import NodeGrantAuthority
from audiagentic.components.agents.gateway.node.drain import NodeDrainEligibility
from audiagentic.components.agents.gateway.service.contract import GATEWAY_SERVICE_KEY
from audiagentic.components.agents.gateway.service.shared_config import load_shared_server_config
from audiagentic.foundation.system.managed_service import ManagedServiceStore
config = load_shared_server_config(Path(sys.argv[1]))
authority = NodeGrantAuthority(config)
eligibility = NodeDrainEligibility(config, ManagedServiceStore(GATEWAY_SERVICE_KEY, root=config.service_root))
assert not eligibility.eligible(config, config.nodes[0])
"""
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[3] / "src"))
    result = subprocess.run(
        [sys.executable, "-c", script, str(config.config_path)],
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr


def test_host_reexports_exact_component_contract_key():
    from audiagentic.components.agents.gateway.service import contract, host

    assert host.GATEWAY_SERVICE_KEY is contract.GATEWAY_SERVICE_KEY
