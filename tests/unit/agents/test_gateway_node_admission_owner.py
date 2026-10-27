"""Canonical node admission with real grant, service, record and session stores."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import yaml

from audiagentic.components.agents.agents_paths import gateway_node_admission_path
from audiagentic.components.agents.gateway import profiles, store
from audiagentic.components.agents.gateway.node import admission_owner as module
from audiagentic.components.agents.gateway.node.admission_contract import (
    NodeSubmissionContext,
    SourceWorkspaceIdentity,
)
from audiagentic.components.agents.gateway.node.authority import NodeGrantAuthority
from audiagentic.components.agents.gateway.queue.work_index import recover_work_index_entries
from audiagentic.components.agents.gateway.service.contract import (
    GATEWAY_SERVICE_KEY,
    PROTOCOL_VERSION,
)
from audiagentic.components.agents.gateway.service.shared_config import load_shared_server_config
from audiagentic.components.agents.gateway.session import sessions_store
from audiagentic.components.agents.models.execution_profile import ExecutionProfile
from audiagentic.components.agents.models.prompt_definition import PromptDefinition, PromptTextPart
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.system.managed_service import ManagedServiceStore


@pytest.fixture
def admission(tmp_path, monkeypatch):
    (tmp_path / "project").mkdir()
    (tmp_path / "service").mkdir()
    for name in ("caller", "node"):
        path = tmp_path / f"{name}.token"
        path.write_text(f"credential-{name}")
        path.chmod(0o600)
    raw = {"schema-version": 1, "server-id": "server", "listen": {"port": 8000},
        "service-root": "service", "node-listen": {"port": 8001},
        "projects": {"project": "project"},
        "principals": {"caller": {"token-file": "caller.token", "projects": ["project"], "actions": ["submit"]}},
        "nodes": {"node": {"token-file": "node.token", "workspaces": {"workspace": "project"},
                           "principals": ["caller"], "revision": 1, "enabled": True}}}
    path = tmp_path / "server.yaml"
    path.write_text(yaml.safe_dump(raw))
    config = load_shared_server_config(path)
    service = ManagedServiceStore(GATEWAY_SERVICE_KEY, root=config.service_root)
    created = service.create(protocol_version=PROTOCOL_VERSION, owner_epoch="owner")
    service.transition("running", expected_revision=created.revision, expected_epoch=created.owner_epoch)
    authority = NodeGrantAuthority(config)
    registry = profiles.InMemoryExecutionProfileRegistry()
    registry.register("profile", provider_id="provider", instances=("source",))
    monkeypatch.setattr(profiles, "_gateway_registry", registry)
    prompt = PromptDefinition("prompt", "", (PromptTextPart("Review {{ user_prompt }}"),))
    selected = SimpleNamespace(execution_profile_id="profile", prompt_profile_id="prompt",
        composition_fingerprint="a" * 64, prompt_definition_fingerprint="b" * 64,
        composition=SimpleNamespace(prompt=prompt, execution_profile=ExecutionProfile("profile", "provider", ("source",))),
        catalog=SimpleNamespace(document=SimpleNamespace(prompts=(prompt,))), config_root=tmp_path)
    resolver = Mock(return_value=selected)
    monkeypatch.setattr(module, "resolve_agent_semantics", resolver)
    queue = Mock()
    queue.enqueue_node.side_effect = lambda root, record, **kwargs: record
    owner = module.NodeAdmissionOwner(config, authority, service, queue, Mock())
    context = NodeSubmissionContext("caller", "server", "project", "node", "workspace",
        SourceWorkspaceIdentity(1, "node", "workspace", "read-write", "c" * 64),
        "/foreign/worktree-not-on-server", "credential-node")
    return SimpleNamespace(owner=owner, context=context, root=config.projects["project"].resolve(),
        queue=queue, resolver=resolver, registry=registry, service=service, authority=authority,
        config_path=path, raw=raw)


def submit(state, **changes):
    arguments = {"agent_id": "reviewer", "prompt_body": "inspect the code",
                 "metadata": {"idempotency_key": "one-key"}, **changes}
    return state.owner.submit(state.root, context=state.context, arguments=arguments, owner_epoch="owner")


def test_fresh_admission_retains_private_source_without_credential(admission):
    record = submit(admission)
    raw = gateway_node_admission_path(admission.root, record["request-id"]).read_bytes()
    private = json.loads(raw)
    assert record["node-admission"]["snapshot-sha256"] == hashlib.sha256(raw).hexdigest()
    assert private["caller-root"] == admission.context.caller_root
    assert private["expanded-prompt"] == "Review {{ user_prompt }}"
    assert "credential-node" not in raw.decode()
    assert admission.context.caller_root not in json.dumps(record)
    assert "one-key" not in json.dumps(record)
    session = sessions_store.read_session_record(admission.root, record["session-id"])
    assert session["created-by-request-id"] == record["request-id"]
    assert record["manifest-id"] is None
    admission.queue.enqueue_node.assert_called_once()


def test_exact_replay_does_not_write_or_enqueue(admission, monkeypatch):
    first = submit(admission)
    for owner, name in ((module, "atomic_write_bytes"), (sessions_store, "write_session_record")):
        monkeypatch.setattr(owner, name, Mock(side_effect=AssertionError("replay must not write")))
    replay = submit(admission)
    assert replay["request-id"] == first["request-id"]
    admission.queue.enqueue_node.assert_called_once()


@pytest.mark.parametrize("change", ["prompt", "source"])
def test_changed_execution_intent_conflicts_without_second_queue(admission, change):
    submit(admission)
    if change == "source":
        admission.context = replace(admission.context,
            source_workspace=replace(admission.context.source_workspace, binding_sha256="d" * 64))
    with pytest.raises(AudiaGenticError) as error:
        submit(admission, **({"prompt_body": "other prompt"} if change == "prompt" else {}))
    assert error.value.code == "CON-AGW-081"
    admission.queue.enqueue_node.assert_called_once()


@pytest.mark.parametrize("credential", ["invalid", "credential-caller"])
def test_invalid_source_creates_nothing_and_does_not_resolve_semantics(admission, credential):
    admission.context = replace(admission.context, source_node_token=credential)
    with pytest.raises(AudiaGenticError):
        submit(admission)
    admission.resolver.assert_not_called()
    admission.queue.enqueue_node.assert_not_called()
    assert store.list_records(admission.root) == []


def test_revocation_between_resolution_and_admission_prevents_writes(admission):
    selected = admission.resolver.return_value
    def revoke(*args):
        admission.raw["nodes"]["node"].update(enabled=False, revision=2)
        admission.config_path.write_text(yaml.safe_dump(admission.raw))
        return selected
    admission.resolver.side_effect = revoke
    with pytest.raises(AudiaGenticError):
        submit(admission)
    assert store.list_records(admission.root) == []
    admission.queue.enqueue_node.assert_not_called()


def test_snapshot_failure_does_not_create_canonical_work(admission, monkeypatch):
    monkeypatch.setattr(module, "atomic_write_bytes", Mock(side_effect=OSError("disk full")))
    with pytest.raises(OSError, match="disk full"):
        submit(admission)
    assert store.list_records(admission.root) == []
    admission.queue.enqueue_node.assert_not_called()


def test_queue_failure_preserves_admitted_record_and_replay_never_redispatches(admission):
    admission.queue.enqueue_node.side_effect = RuntimeError("queue unavailable")
    with pytest.raises(RuntimeError, match="queue unavailable"):
        submit(admission)
    record, = store.list_records(admission.root)
    assert record["state"] == "queued"
    entries, quarantined = recover_work_index_entries(admission.service.root, live_owner_epoch="owner")
    assert quarantined == 0
    assert [(entry.request_id, entry.phase) for entry in entries] == [(record["request-id"], "admitted")]
    assert submit(admission)["request-id"] == record["request-id"]
    admission.queue.enqueue_node.assert_called_once()


def test_replay_missing_snapshot_requires_reconciliation(admission):
    record = submit(admission)
    gateway_node_admission_path(admission.root, record["request-id"]).unlink()
    with pytest.raises(AudiaGenticError, match="snapshot is unavailable"):
        submit(admission)
    admission.queue.enqueue_node.assert_called_once()


def test_replay_rejects_changed_private_locator_without_rewriting(admission):
    first = submit(admission)
    path = gateway_node_admission_path(admission.root, first["request-id"])
    original = path.read_bytes()
    admission.context = replace(admission.context, caller_root="/other/foreign-workspace")
    with pytest.raises(AudiaGenticError, match="caller locator"):
        submit(admission)
    assert path.read_bytes() == original
    admission.queue.enqueue_node.assert_called_once()


def test_replay_allows_audit_metadata_changes(admission):
    first = submit(admission)
    replay = submit(admission, source="another-audit-source", title="Different audit title")
    assert first["request-id"] == replay["request-id"]
    admission.queue.enqueue_node.assert_called_once()


def test_replay_corrupt_snapshot_cannot_rewrite_or_redispatch(admission):
    first = submit(admission)
    path = gateway_node_admission_path(admission.root, first["request-id"])
    path.write_bytes(b"corrupt")
    with pytest.raises(AudiaGenticError, match="canonical authority"):
        submit(admission)
    assert path.read_bytes() == b"corrupt"
    admission.queue.enqueue_node.assert_called_once()


def test_hash_matched_but_invalid_private_schema_is_rejected(admission):
    first = submit(admission)
    path = gateway_node_admission_path(admission.root, first["request-id"])
    # Model a storage fault where hash integrity alone is insufficient.
    raw = b"{}"
    path.write_bytes(raw)
    record = dict(first)
    descriptor = dict(first["node-admission"])
    descriptor["snapshot-sha256"] = hashlib.sha256(raw).hexdigest()
    record["node-admission"] = descriptor
    with pytest.raises(AudiaGenticError, match="snapshot is invalid"):
        module._read_snapshot(admission.root, record, admission.context)


@pytest.mark.parametrize("redirect", ["file", "parent"])
def test_replay_rejects_redirected_private_evidence(admission, tmp_path, redirect):
    first = submit(admission)
    path = gateway_node_admission_path(admission.root, first["request-id"])
    original = path.read_bytes()
    target = tmp_path / "redirected"
    if redirect == "file":
        target.write_bytes(original)
        path.unlink()
        link = path
    else:
        target.mkdir()
        (target / path.name).write_bytes(original)
        path.unlink()
        path.parent.rmdir()
        link = path.parent
    try:
        link.symlink_to(target, target_is_directory=redirect == "parent")
    except OSError as error:
        pytest.skip(f"Platform does not permit test symlinks: {error.winerror if hasattr(error, 'winerror') else error.errno}")
    with pytest.raises(AudiaGenticError, match="links or reparse"):
        submit(admission)
    admission.queue.enqueue_node.assert_called_once()


@pytest.mark.skipif(os.name != "nt", reason="Windows junction qualification")
def test_initial_snapshot_rejects_junction_parent_before_any_write(admission, tmp_path, monkeypatch):
    request_id = "req_test_admission"
    monkeypatch.setattr(store, "generate_request_id", lambda root: request_id)
    path = gateway_node_admission_path(admission.root, request_id)
    outside = tmp_path / "junction-target"
    outside.mkdir()
    path.parent.parent.mkdir(parents=True)
    linked = subprocess.run(["cmd", "/c", "mklink", "/J", str(path.parent), str(outside)],
        capture_output=True, text=True, timeout=10)
    assert linked.returncode == 0, linked.stderr
    try:
        assert path.parent.is_junction()
        with pytest.raises(AudiaGenticError, match="links or reparse"):
            submit(admission)
        assert list(outside.iterdir()) == []
        assert store.list_records(admission.root) == []
        admission.queue.enqueue_node.assert_not_called()
    finally:
        if path.parent.is_junction():
            path.parent.rmdir()  # Remove only this verified test junction.


def test_registry_change_before_commit_prevents_canonical_mutation(admission):
    admission.registry.validate_snapshot_current = Mock(return_value=False)
    with pytest.raises(AudiaGenticError, match="profile changed"):
        submit(admission)
    assert store.list_records(admission.root) == []
    admission.queue.enqueue_node.assert_not_called()


@pytest.mark.parametrize("change", [{"session_id": "existing"}, {"session_keep_alive": True},
                                   {"mode": "blocking"}, {"context_override": True}])
def test_unsupported_owned_node_modes_do_not_create_work(admission, change):
    with pytest.raises(AudiaGenticError):
        submit(admission, **change)
    assert store.list_records(admission.root) == []
    admission.queue.enqueue_node.assert_not_called()


def test_queue_runs_outside_service_and_grant_locks(admission):
    def enqueue(root, record, **kwargs):
        with admission.service.owner_guard("owner"):
            admission.authority.authorize_admission(principal_id="caller", server_project_id="project",
                node_id="node", workspace_id="workspace", source_workspace=admission.context.source_workspace,
                source_node_token="credential-node", callback=lambda placement: None)
        return record
    admission.queue.enqueue_node.side_effect = enqueue
    assert submit(admission)["state"] == "queued"
