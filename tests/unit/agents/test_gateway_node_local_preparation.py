"""Concrete node preparation binds configured roots and all private worker inputs."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import yaml

from audiagentic.components.agents.agents_paths import global_agents_config_path
from audiagentic.components.agents.contracts.execution_context import ExecutionManifest, SessionSpec
from audiagentic.components.agents.contracts.worker_protocol import (
    WorkerExecuteEnvelope,
    WorkerExecutionIdentity,
)
from audiagentic.components.agents.gateway import profiles
from audiagentic.components.agents.gateway.admission import (
    context,
    instructions,
    local_dispatch,
    semantics,
)
from audiagentic.components.agents.gateway.node.contracts import canonical_json
from audiagentic.components.agents.gateway.node.local_preparation import NodeLocalPreparer
from audiagentic.components.agents.gateway.node.preparation import (
    PreparationBinding,
    PromptSemanticIdentity,
    RetainedNodePreparation,
)
from audiagentic.components.agents.gateway.service.shared_config import (
    SharedGatewayNodeConfig,
    SharedGatewayNodeWorkspace,
)
from audiagentic.components.providers import providers_api
from audiagentic.foundation.contracts.errors import AudiaGenticError


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


@pytest.fixture
def setup(tmp_path, monkeypatch):
    root = tmp_path / "workspace"
    root.mkdir()
    path = global_agents_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "contract-version": "v2",
        "prompts": {"main": {"content": [{"kind": "file", "path": "instructions.txt"}, {"kind": "text", "text": "Task {prompt-body}; {project.name}; {source_control.branch}"}]}},
        "roles": {"reader": {"instructions": "Read"}},
        "execution_profiles": {"native": {"provider_id": "codex", "instances": ["source-a"], "model_alias": "native-alias", "params": {"temperature": 0.1}, "is_default": True}},
        "agents": {"reader": {"name": "Reader", "prompt_id": "main", "role_ids": ["reader"], "execution_profile_id": "native"}},
    }
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    (path.parent / "instructions.txt").write_text("PRIVATE instructions", encoding="utf-8")
    monkeypatch.setattr(profiles, "_gateway_registry", profiles.load_gateway_registry_from_agents_catalog())
    token = tmp_path / "node.token"
    token.write_text("private-token")
    config = SharedGatewayNodeConfig("node", "server", "https://gateway.example", token, tmp_path / "state", {"workspace": SharedGatewayNodeWorkspace(root, frozenset({"native"}))})
    binding = PreparationBinding("command", "request", "node", "node-epoch", "owner", 1, "workspace", 1, 1, "challenge", "preparation-request")
    raw = "RAW body λ"
    selected = semantics.resolve_agent_semantics("reader")
    expanded = instructions.expand_agent_prompt(selected.composition.prompt, prompts=selected.catalog.document.prompts, config_root=selected.config_root)
    semantic = PromptSemanticIdentity(selected.composition_fingerprint, selected.prompt_definition_fingerprint, "main", "native", expanded.version, expanded.sha256, sha(raw))
    capacity = Mock(side_effect=lambda root, ids: {key: {"model-id": "catalog-model"} for key in ids})
    provider_config = Mock(return_value={"enabled": True, "config": {"native-option": "local"}})
    tier = Mock(return_value="full-isolation")
    model = Mock(return_value={"model-id": "native-model"})
    enabled = Mock(return_value=True)
    monkeypatch.setattr(providers_api, "resolve_instance_capacity", capacity)
    monkeypatch.setattr(providers_api, "get_provider_runtime_config_state", provider_config)
    monkeypatch.setattr(providers_api, "get_provider_execution_isolation_tier", tier)
    monkeypatch.setattr(providers_api, "resolve_launch_model", model)
    monkeypatch.setattr(providers_api, "is_provider_enabled_for_launch", enabled)
    kwargs = dict(binding=binding, semantic=semantic, agent_id="reader", raw_prompt=raw, worker_id="worker", attempt_epoch=2)
    return SimpleNamespace(root=root, path=path, data=data, config=config, binding=binding, semantic=semantic, raw=raw, kwargs=kwargs, capacity=capacity, provider_config=provider_config, tier=tier, model=model, enabled=enabled)


def preparer(setup, **kwargs):
    return NodeLocalPreparer(setup.config, component_profile="node-process", **kwargs)


def private(prepared):
    return json.loads(prepared._provider_manifest)


def test_complete_private_packet_and_attestation_bind_all_owned_inputs(setup):
    result = preparer(setup).prepare(**setup.kwargs)
    assert type(result) is RetainedNodePreparation
    payload = private(result)
    assert set(payload) == {"version", "kind", "worker-identity", "execution-manifest", "provider-request"}
    assert payload["version"] == 1 and payload["kind"] == "node-worker-preparation"
    assert canonical_json(payload) == result._provider_manifest
    assert hashlib.sha256(result._provider_manifest).hexdigest() == result.attestation.provider_manifest_sha256
    manifest = ExecutionManifest.from_mapping(payload["execution-manifest"])
    identity = WorkerExecutionIdentity.from_mapping(payload["worker-identity"], tier_field="provider-isolation-tier")
    request = providers_api.ProviderExecutionRequest.from_mapping(payload["provider-request"])
    WorkerExecuteEnvelope(identity, request.to_mapping())
    assert manifest.request_id == setup.binding.request_id == request.packet_data["request-id"]
    assert manifest.manifest_id == identity.manifest_id == result.attestation.manifest_id
    assert manifest.context_fingerprint == identity.context_fingerprint == result.attestation.context_fingerprint
    assert request.project_root == setup.root.resolve()
    assert request.packet_data["working-root"] == str(setup.root.resolve())
    assert identity.project_root == str(setup.root.resolve())
    assert identity.component_profile == "node-process"
    assert identity.worker_id == request.worker_id == "worker"
    assert identity.attempt_epoch == request.attempt_epoch == 2
    assert request.model_id == result.attestation.model_id == manifest.identity.model_id == "native-model"
    assert request.model_alias == result.attestation.model_alias == "native-alias"
    assert request.packet_data["params"] == {"temperature": 0.1}
    assert request.packet_data["prompt-body"] == result._rendered_prompt
    assert manifest.prompt_digest == sha(setup.raw)
    assert sha(result._rendered_prompt) == result.attestation.rendered_prompt_sha256
    assert "PRIVATE" not in repr(result) and str(setup.root) not in repr(result)
    setup.model.assert_called_once_with(setup.root.resolve(), provider_id="codex", model_id="catalog-model", model_alias="native-alias")


def test_one_expansion_is_compared_before_any_provider_facts(setup, monkeypatch):
    events = []
    expand = instructions.expand_agent_prompt
    def expanded(*args, **kwargs):
        events.append("expand")
        value = expand(*args, **kwargs)
        (setup.path.parent / "instructions.txt").write_text("CHANGED after expansion", encoding="utf-8")
        return value
    spy = Mock(side_effect=expanded)
    monkeypatch.setattr(instructions, "expand_agent_prompt", spy)
    resolve_profile = local_dispatch.resolve_local_profile
    def profile(*args, **kwargs):
        events.append("profile")
        return resolve_profile(*args, **kwargs)
    monkeypatch.setattr(local_dispatch, "resolve_local_profile", profile)
    result = preparer(setup).prepare(**setup.kwargs)
    assert result.attestation.semantic.expanded_prompt_sha256 == setup.semantic.expanded_prompt_sha256
    assert result._rendered_prompt.startswith("PRIVATE instructions")
    spy.assert_called_once()
    assert events == ["expand", "profile"]


@pytest.mark.parametrize("field,value", [
    ("composition_fingerprint", "a" * 64), ("prompt_definition_fingerprint", "a" * 64),
    ("prompt_id", "other"), ("execution_profile_id", "other"),
    ("expanded_prompt_sha256", "a" * 64), ("raw_prompt_sha256", "a" * 64),
])
def test_every_selected_semantic_field_rejected_before_profile_or_provider(setup, monkeypatch, field, value):
    if field == "execution_profile_id":
        setup.config = replace(setup.config, workspaces={"workspace": SharedGatewayNodeWorkspace(setup.root, frozenset({"native", "other"}))})
    profile = Mock(side_effect=AssertionError("profile facts must not be read"))
    monkeypatch.setattr(local_dispatch, "resolve_local_profile", profile)
    with pytest.raises(AudiaGenticError):
        preparer(setup).prepare(**{**setup.kwargs, "semantic": replace(setup.semantic, **{field: value})})
    profile.assert_not_called()
    setup.provider_config.assert_not_called()
    setup.capacity.assert_not_called()
    setup.model.assert_not_called()


def test_changed_file_content_rejected_before_provider_facts(setup):
    (setup.path.parent / "instructions.txt").write_text("Changed expanded dependency", encoding="utf-8")
    with pytest.raises(AudiaGenticError, match="CON-AGND-001"):
        preparer(setup).prepare(**setup.kwargs)
    setup.capacity.assert_not_called()
    setup.provider_config.assert_not_called()


@pytest.mark.parametrize("node_id,workspace", [("wrong-node", "workspace"), ("node", "../wire-root"), ("node", "unknown")])
def test_binding_cannot_select_unconfigured_root(setup, node_id, workspace):
    if workspace.startswith("../"):
        with pytest.raises(AudiaGenticError):
            replace(setup.binding, workspace_id=workspace)
        return
    with pytest.raises(AudiaGenticError, match="CON-AGND-001"):
        preparer(setup).prepare(**{**setup.kwargs, "binding": replace(setup.binding, node_id=node_id, workspace_id=workspace)})
    setup.capacity.assert_not_called()


def test_wire_metadata_source_and_root_argument_cannot_override_owned_execution(setup):
    owner = preparer(setup)
    with pytest.raises(TypeError, match="project_root"):
        owner.prepare(**setup.kwargs, project_root="/wire/attacker")
    result = owner.prepare(**setup.kwargs, source="/wire/attacker", metadata={"working-root": "/wire/attacker", "project-root": "/wire/attacker", "component-profile": "wire-profile"})
    payload = private(result)
    assert payload["provider-request"]["project-root"] == str(setup.root.resolve())
    assert payload["provider-request"]["packet-data"]["working-root"] == str(setup.root.resolve())
    assert payload["worker-identity"]["component-profile"] == "node-process"
    assert payload["execution-manifest"]["identity"]["component_profile"] == "node-process"


def test_missing_registry_never_enables_test_fallback_or_installs_registry(setup, monkeypatch):
    monkeypatch.setattr(profiles, "_gateway_registry", None)
    with pytest.raises(AudiaGenticError, match="IO-AGW-108"):
        preparer(setup).prepare(**setup.kwargs)
    assert profiles.get_gateway_registry() is None
    setup.capacity.assert_not_called()


@pytest.mark.parametrize("changed", [
    {"provider_id": "other-provider"}, {"instances": ("other-instance",)},
    {"execution_params": {"temperature": 0.9}},
])
def test_installed_registry_drift_fails_before_execution_facts(setup, changed):
    options = dict(provider_id="codex", instances=("source-a",), execution_params={"temperature": 0.1})
    profiles.get_gateway_registry().register("native", **{**options, **changed})
    with pytest.raises(AudiaGenticError, match="CON-AGND-001"):
        preparer(setup).prepare(**setup.kwargs)
    setup.capacity.assert_not_called()
    setup.provider_config.assert_not_called()
    setup.model.assert_not_called()


def test_catalog_re_read_drift_from_selected_semantics_is_rejected(setup, monkeypatch):
    materialize = local_dispatch.materialize_local_prompt
    def changed(**kwargs):
        result = materialize(**kwargs)
        setup.data["execution_profiles"]["native"]["model_alias"] = "changed-alias"
        setup.path.write_text(yaml.safe_dump(setup.data), encoding="utf-8")
        return result
    monkeypatch.setattr(local_dispatch, "materialize_local_prompt", changed)
    with pytest.raises(AudiaGenticError, match="CON-AGND-001"):
        preparer(setup).prepare(**setup.kwargs)
    setup.capacity.assert_not_called()


@pytest.mark.parametrize("tier", ["partial-isolation", "no-isolation"])
def test_unsupported_isolation_rejected_without_launch_model_or_effect(setup, tier):
    setup.tier.return_value = tier
    with pytest.raises(AudiaGenticError, match="full-isolation"):
        preparer(setup).prepare(**setup.kwargs)
    setup.model.assert_not_called()


@pytest.mark.parametrize("kwargs", [
    {"mode": "blocking"}, {"session": SessionSpec(session_id="session")},
    {"session": SessionSpec(keep_alive=True)}, {"session": SessionSpec(idle_timeout_seconds=10)},
    {"provider_chat_url": "https://chatgpt.com/g/project/c/conversation"},
])
def test_server_session_modes_explicitly_rejected_before_facts(setup, kwargs):
    with pytest.raises(AudiaGenticError, match="isolated worker turns"):
        preparer(setup).prepare(**{**setup.kwargs, **kwargs})
    setup.capacity.assert_not_called()


@pytest.mark.parametrize("model", [None, "", " ", "bad\nmodel", 42])
def test_no_model_fabrication_when_public_launch_resolution_not_concrete(setup, model):
    setup.model.return_value = {"model-id": model}
    with pytest.raises(AudiaGenticError, match="concrete model-id"):
        preparer(setup).prepare(**setup.kwargs)


def test_surface_selection_and_multi_instance_modes_rejected(setup, monkeypatch):
    original = local_dispatch.resolve_local_profile
    def unsupported(*args, **kwargs):
        value = original(*args, **kwargs)
        return replace(value, snapshot=replace(value.snapshot, resolved_surface_id="unsupported-surface"))
    monkeypatch.setattr(local_dispatch, "resolve_local_profile", unsupported)
    with pytest.raises(AudiaGenticError, match="session surfaces"):
        preparer(setup).prepare(**setup.kwargs)
    setup.capacity.assert_not_called()


def test_multi_instance_catalog_has_no_node_scheduler(setup):
    setup.data["execution_profiles"]["native"]["instances"] = ["source-a", "source-b"]
    setup.path.write_text(yaml.safe_dump(setup.data), encoding="utf-8")
    selected = semantics.resolve_agent_semantics("reader")
    selected_semantic = replace(setup.semantic, composition_fingerprint=selected.composition_fingerprint)
    registry = profiles.get_gateway_registry()
    registry.register("native", provider_id="codex", instances=("source-a", "source-b"), execution_params={"temperature": 0.1})
    with pytest.raises(AudiaGenticError, match="single selected model instance"):
        preparer(setup).prepare(**{**setup.kwargs, "semantic": selected_semantic})
    setup.capacity.assert_not_called()


def test_preparation_writes_no_files_and_invokes_no_native_or_worker(setup, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("preparation attempted an effect")
    before = {p: p.read_bytes() for base in (setup.root, setup.path.parent) for p in base.rglob("*") if p.is_file()}
    monkeypatch.setattr(Path, "write_text", forbidden)
    monkeypatch.setattr(Path, "write_bytes", forbidden)
    monkeypatch.setattr(Path, "mkdir", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(providers_api, "execute_provider_turn", forbidden)
    monkeypatch.setattr(providers_api, "prepare_provider_execution_environment", forbidden)
    preparer(setup).prepare(**setup.kwargs)
    after = {p: p.read_bytes() for base in (setup.root, setup.path.parent) for p in base.rglob("*") if p.is_file()}
    assert after == before
    assert not setup.config.state_root.exists()


def test_different_configured_roots_and_local_git_context_share_selected_semantics(setup):
    from dulwich import porcelain
    from dulwich.repo import Repo

    roots = [setup.root, setup.root.parent / "other-workspace"]
    roots[1].mkdir()
    for index, root in enumerate(roots):
        repo = Repo.init(str(root))
        repo.refs.set_symbolic_ref(b"HEAD", f"refs/heads/branch-{index}".encode())
        repo.close()
        porcelain.commit(str(root), message=b"local context", author=b"Test <test@example.invalid>", committer=b"Test <test@example.invalid>")
    rendered = []
    contexts = []
    for root in roots:
        configured = replace(setup.config, workspaces={"workspace": SharedGatewayNodeWorkspace(root, frozenset({"native"}))})
        result = NodeLocalPreparer(configured, component_profile="node-process").prepare(**setup.kwargs)
        assert result.attestation.semantic == setup.semantic
        rendered.append(result._rendered_prompt)
        contexts.append(result.attestation.context_fingerprint)
        assert private(result)["provider-request"]["project-root"] == str(root.resolve())
    assert "branch-0" in rendered[0] and "branch-1" in rendered[1]
    assert contexts[0] != contexts[1]
    assert rendered[0] != rendered[1]


def test_owner_import_never_composes_gateway_queue_or_runtime():
    script = '''
import importlib.abc
import sys
class Guard(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(("audiagentic.runtime", "audiagentic.components.agents.gateway.api", "audiagentic.components.agents.gateway.queue", "audiagentic.components.agents.gateway.session", "audiagentic.components.agents.gateway.store")):
            raise AssertionError("effect owner imported: " + fullname)
sys.meta_path.insert(0, Guard())
from audiagentic.components.agents.gateway.node.local_preparation import NodeLocalPreparer
'''
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[3] / "src"))
    result = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr



def test_selected_named_surface_rejected_before_provider_resolution(setup, monkeypatch):
    setup.data["execution_profiles"]["native"]["surface_id"] = "named-session-surface"
    setup.path.write_text(yaml.safe_dump(setup.data), encoding="utf-8")
    selected = semantics.resolve_agent_semantics("reader")
    semantic = replace(setup.semantic, composition_fingerprint=selected.composition_fingerprint)
    resolve = Mock(side_effect=AssertionError("surface provider resolution must not run"))
    monkeypatch.setattr(providers_api, "resolve_session_surface", resolve)
    with pytest.raises(AudiaGenticError, match="provider-session surfaces"):
        preparer(setup).prepare(**{**setup.kwargs, "semantic": semantic})
    resolve.assert_not_called()
    setup.capacity.assert_not_called()


def test_configured_workspace_profile_allowlist_is_enforced(setup):
    setup.config = replace(setup.config, workspaces={"workspace": SharedGatewayNodeWorkspace(setup.root, frozenset({"another"}))})
    with pytest.raises(AudiaGenticError, match="not allowed in this workspace"):
        preparer(setup).prepare(**setup.kwargs)
    setup.capacity.assert_not_called()


def test_relative_or_missing_configured_root_rejected(setup):
    for root in (Path("relative"), setup.root / "absent"):
        config = replace(setup.config, workspaces={"workspace": SharedGatewayNodeWorkspace(root, frozenset({"native"}))})
        with pytest.raises(AudiaGenticError, match="Configured node workspace root"):
            NodeLocalPreparer(config).prepare(**setup.kwargs)
    setup.capacity.assert_not_called()


def test_expanded_version_is_a_closed_contract_before_preparation(setup):
    with pytest.raises(AudiaGenticError, match="expanded-prompt-version"):
        replace(setup.semantic, expanded_prompt_version=2)
    setup.capacity.assert_not_called()


def test_process_component_profile_frozen_at_composition_not_wire(setup, monkeypatch):
    monkeypatch.setenv("AUDIAGENTIC_COMPONENT_PROFILE", "process-profile")
    owner = NodeLocalPreparer(setup.config)
    monkeypatch.setenv("AUDIAGENTIC_COMPONENT_PROFILE", "later-environment")
    result = owner.prepare(**setup.kwargs, metadata={"component-profile": "wire-profile"})
    assert private(result)["worker-identity"]["component-profile"] == "process-profile"


def test_injected_component_reader_runs_before_baseline_and_semantics(setup, monkeypatch):
    events = []
    def reader(root):
        events.append("reader")
        assert root == setup.root.resolve()
        return {"project": {"name": "old", "extra": "rich"}, "source_control": {"branch": "component-branch"}}
    original = context.baseline_agent_template_context
    def baseline(*args, **kwargs):
        events.append("baseline")
        return original(*args, **kwargs)
    monkeypatch.setattr(context, "baseline_agent_template_context", baseline)
    original_semantics = semantics.resolve_agent_semantics
    def resolve(agent):
        events.append("semantics")
        return original_semantics(agent)
    monkeypatch.setattr(semantics, "resolve_agent_semantics", resolve)
    result = preparer(setup, component_context_reader=reader).prepare(**setup.kwargs)
    assert events == ["reader", "baseline", "semantics"]
    packet = private(result)["provider-request"]["packet-data"]
    assert packet["template-context"]["project"]["name"] != "old"
    assert packet["template-context"]["project"]["extra"] == "rich"
    assert "component-branch" in result._rendered_prompt



@pytest.mark.parametrize("keys,value", [
    (("provider-request", "packet-data", "params", "temperature"), 0.9),
    (("provider-request", "packet-data", "prompt-body"), "changed render"),
    (("provider-request", "project-root"), "/different/local/root"),
    (("worker-identity", "project-root"), "/different/local/root"),
    (("worker-identity", "attempt-epoch"), 99),
])
def test_private_packet_substitution_cannot_keep_original_attestation(setup, keys, value):
    result = preparer(setup).prepare(**setup.kwargs)
    payload = private(result)
    cursor = payload
    for key in keys[:-1]:
        cursor = cursor[key]
    cursor[keys[-1]] = value
    with pytest.raises(AudiaGenticError, match="CON-AGND-001"):
        replace(result, _provider_manifest=canonical_json(payload))


def test_alias_only_source_uses_public_launch_resolution_without_inventing_model(setup):
    setup.capacity.side_effect = None
    setup.capacity.return_value = {"source-a": {"model-id": None}}
    result = preparer(setup).prepare(**setup.kwargs)
    setup.model.assert_called_once_with(setup.root.resolve(), provider_id="codex", model_id=None, model_alias="native-alias")
    assert result.attestation.model_id == "native-model"



@pytest.mark.parametrize("provider", ["renamed-worker", "gpt-auto-renamed-worker"])
@pytest.mark.parametrize("tier", ["full-isolation", "no-isolation"])
def test_provider_names_do_not_route_preparation_public_isolation_facts_do(setup, monkeypatch, provider, tier):
    setup.data["execution_profiles"]["native"]["provider_id"] = provider
    setup.path.write_text(yaml.safe_dump(setup.data), encoding="utf-8")
    profiles.get_gateway_registry().register("native", provider_id=provider, instances=("source-a",), execution_params={"temperature": 0.1})
    selected = semantics.resolve_agent_semantics("reader")
    semantic = replace(setup.semantic, composition_fingerprint=selected.composition_fingerprint)
    setup.tier.return_value = tier
    native = Mock(side_effect=AssertionError("preparation must never invoke a native provider"))
    monkeypatch.setattr(providers_api, "execute_provider_turn", native)
    monkeypatch.setattr(providers_api, "prepare_provider_execution_environment", native)
    monkeypatch.setattr(subprocess, "Popen", native)
    kwargs = {**setup.kwargs, "semantic": semantic}
    if tier == "full-isolation":
        result = preparer(setup).prepare(**kwargs)
        assert result.attestation.provider_id == provider
        assert private(result)["provider-request"]["provider-isolation-tier"] == tier
        setup.model.assert_called_once()
    else:
        with pytest.raises(AudiaGenticError, match="full-isolation"):
            preparer(setup).prepare(**kwargs)
        setup.model.assert_not_called()
    setup.tier.assert_called_once_with(provider)
    native.assert_not_called()



def test_disabled_provider_preflight_rejects_before_packet_attestation_or_native(setup, monkeypatch):
    from audiagentic.components.agents.gateway.node import local_preparation

    setup.enabled.return_value = False
    # The public narrow boolean remains authoritative even when the earlier
    # runtime-config read differs. These reads do not claim atomicity.
    setup.provider_config.return_value = {"enabled": True, "config": {"native-option": "local"}}
    native = Mock(side_effect=AssertionError("disabled provider must not execute"))
    packet = Mock(side_effect=AssertionError("disabled provider must not build a packet"))
    attestation = Mock(side_effect=AssertionError("disabled provider must not attest"))
    monkeypatch.setattr(providers_api, "execute_provider_turn", native)
    monkeypatch.setattr(providers_api, "prepare_provider_execution_environment", native)
    monkeypatch.setattr(subprocess, "Popen", native)
    monkeypatch.setattr(local_preparation, "build_provider_packet", packet)
    monkeypatch.setattr(local_preparation, "prepare_node_command", attestation)
    with pytest.raises(AudiaGenticError, match="VAL-AGW-031") as error:
        preparer(setup).prepare(**setup.kwargs)
    assert error.value.details == {"provider-id": "codex"}
    setup.enabled.assert_called_once_with(setup.root.resolve(), "codex")
    setup.model.assert_not_called()
    packet.assert_not_called()
    attestation.assert_not_called()
    native.assert_not_called()
    assert not setup.config.state_root.exists()


def test_enabled_provider_preflight_keeps_existing_runtime_digest(setup):
    result = preparer(setup).prepare(**setup.kwargs)
    setup.enabled.assert_called_once_with(setup.root.resolve(), "codex")
    manifest = private(result)["execution-manifest"]
    assert manifest["identity"]["agent_runtime_digest"] == result.attestation.runtime_digest
    # Runtime configuration is frozen by the existing facts helper once;
    # the narrow launch boolean adds no replacement runtime-digest recipe.
    setup.provider_config.assert_called_once_with(setup.root.resolve(), "codex")
