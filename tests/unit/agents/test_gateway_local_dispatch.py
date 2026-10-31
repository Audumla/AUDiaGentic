"""Stage 1 local materialization parity, authority and admission ordering."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import yaml

from audiagentic.components.agents.agents_paths import global_agents_config_path
from audiagentic.components.agents.configuration import global_catalog
from audiagentic.components.agents.contracts import execution_context
from audiagentic.components.agents.gateway import api, instances, profiles
from audiagentic.components.agents.gateway.admission import (
    context,
    instructions,
    local_dispatch,
    semantics,
)
from audiagentic.components.agents.gateway.session import client_defaults, idle_grace
from audiagentic.components.providers import providers_api
from audiagentic.foundation.contracts.errors import AudiaGenticError


@pytest.fixture
def catalog(tmp_path):
    path = global_agents_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "contract-version": "v2",
        "prompts": {"main": {"content": [{"kind": "file", "path": "instructions.txt"}, {"kind": "text", "text": "{project.name}: {prompt-body}"}]}},
        "roles": {"reader": {"instructions": "Read"}},
        "execution_profiles": {"native": {"provider_id": "codex", "instances": ["source-a"], "is_default": True, "model_alias": "alias", "params": {"temperature": 0.1}}},
        "agents": {"reader": {"name": "Reader", "prompt_id": "main", "role_ids": ["reader"], "execution_profile_id": "native"}},
    }
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    (path.parent / "instructions.txt").write_text("PRIVATE file", encoding="utf-8")
    return path, data


def selection(provider="codex", instance_ids=("source-a",)):
    profile = {"profile_id": "native", "provider_id": provider, "instances": list(instance_ids), "params": {"temperature": 0.1}, "model_alias": "alias"}
    snapshot = profiles.snapshot_from_resolved_profile("native", provider, instance_ids, profile["params"])
    return local_dispatch.LocalProfileSelection(profile, snapshot, None)


def prompt():
    return local_dispatch.materialize_local_prompt(raw_prompt="BODY", semantics=None, template_context={})


@pytest.mark.parametrize("body", ["", "  raw {project.name}\n", "Unicode λ"])
def test_raw_prompt_defaults_and_bytes_are_unchanged(body):
    result = local_dispatch.materialize_local_prompt(raw_prompt=body, semantics=None, template_context={"project": {"name": "ignored"}})
    assert result.text == body
    assert result.template_name == "prompt-definition:default"
    assert result.template_sha256 == hashlib.sha256(body.encode()).hexdigest()
    assert result.prompt_profile_id == "default"
    assert result.composition_fingerprint is None and result.prompt_definition_fingerprint is None
    assert result.expanded is None


def test_raw_none_retains_existing_encode_failure():
    with pytest.raises(AttributeError, match="encode"):
        local_dispatch.materialize_local_prompt(raw_prompt=None, semantics=None, template_context={})


def test_agent_expands_once_retains_frozen_content_and_hides_prompt_repr(catalog, monkeypatch):
    selected = semantics.resolve_agent_semantics("reader")
    original_expand = instructions.expand_agent_prompt
    def expand(*args, **kwargs):
        expanded = original_expand(*args, **kwargs)
        (catalog[0].parent / "instructions.txt").write_text("CHANGED", encoding="utf-8")
        return expanded
    spy = Mock(side_effect=expand)
    monkeypatch.setattr(instructions, "expand_agent_prompt", spy)
    result = local_dispatch.materialize_local_prompt(raw_prompt="BODY", semantics=selected, template_context={"project": {"name": "Local"}, "prompt-body": "must be overridden"})
    assert result.text == "PRIVATE file\nLocal: BODY"
    assert result.expanded.content == "PRIVATE file\n{project.name}: {prompt-body}"
    assert result.expanded.sha256 == hashlib.sha256(result.expanded.content.encode()).hexdigest()
    assert result.template_sha256 == hashlib.sha256(result.text.encode()).hexdigest()
    assert result.template_sha256 != result.expanded.sha256
    assert result.composition_fingerprint == selected.composition_fingerprint
    assert result.prompt_definition_fingerprint == selected.prompt_definition_fingerprint
    assert "PRIVATE" not in repr(result) and "BODY" not in repr(result)
    spy.assert_called_once()


def test_context_reader_then_baseline_and_canonical_name(monkeypatch, tmp_path):
    events = []
    component = {"project": {"name": "old", "extra": "rich"}, "source_control": {"branch": "component"}}
    def reader(root):
        events.append("reader")
        return component
    def baseline(root, *, workspace_name):
        events.append("baseline")
        assert workspace_name == "workspace"
        return {"project": {"name": "canonical"}, "source_control": {"branch": "baseline"}}
    monkeypatch.setattr(context, "baseline_agent_template_context", baseline)
    result = context.build_agent_template_context(tmp_path, component_reader=reader, workspace_name="workspace", agent_id="reader")
    assert events == ["reader", "baseline"]
    assert result == {"project": {"name": "canonical", "extra": "rich"}, "source_control": {"branch": "component"}}
    assert component["project"]["name"] == "old"
    events.clear()
    assert context.build_agent_template_context(tmp_path, component_reader=reader, workspace_name=None, agent_id=None) is component
    assert events == ["reader"]


def test_baseline_failure_precedes_semantics_in_ordinary_api(tmp_path, monkeypatch):
    events = []
    def baseline(*args, **kwargs):
        events.append("baseline")
        raise RuntimeError("baseline failed")
    resolver = Mock(side_effect=AssertionError("semantics must not run"))
    monkeypatch.setattr(context, "baseline_agent_template_context", baseline)
    monkeypatch.setattr(semantics, "resolve_agent_semantics", resolver)
    def reader(root):
        events.append("reader")
        return {}
    with pytest.raises(RuntimeError, match="baseline failed"):
        api.submit_execution_request(tmp_path, agent_id="reader", prompt_body="BODY", component_context_reader=reader)
    assert events == ["reader", "baseline"]
    resolver.assert_not_called()
    assert not hasattr(api, "_resolve_agent_semantics")


@pytest.mark.parametrize("profile_id", [None, "native"])
@pytest.mark.parametrize("hosted", [False, True])
def test_two_global_reads_and_hosted_snapshot_presence_preserved(catalog, tmp_path, monkeypatch, profile_id, hosted):
    registry = profiles.InMemoryExecutionProfileRegistry() if hosted else None
    if registry is not None:
        registry.register("native", provider_id="codex", instances=("source-a",), execution_params={"temperature": 0.1})
    monkeypatch.setattr(profiles, "_gateway_registry", registry)
    reader = Mock(wraps=global_catalog.read_global_agents_config)
    monkeypatch.setattr(global_catalog, "read_global_agents_config", reader)
    result = local_dispatch.resolve_local_profile(tmp_path, profile_id, allow_test_fallback=not hosted)
    assert reader.call_count == 2
    assert result.profile["model_alias"] == "alias"
    assert result.snapshot.profile_id == "native"
    assert result.gateway_snapshot is (result.snapshot if hosted else None)
    # No new registry was created or installed by the helper.
    assert profiles.get_gateway_registry() is registry


def test_production_cannot_use_missing_registry_fallback(catalog, tmp_path, monkeypatch):
    monkeypatch.setattr(profiles, "_gateway_registry", None)
    read = Mock(wraps=global_catalog.read_global_agents_config)
    monkeypatch.setattr(global_catalog, "read_global_agents_config", read)
    with pytest.raises(AudiaGenticError, match="IO-AGW-108"):
        local_dispatch.resolve_local_profile(tmp_path, "native", allow_test_fallback=False)
    assert read.call_count == 2


def fact_dependencies(monkeypatch, events, failure=None):
    def model(root, ids):
        events.append("model")
        if failure == "model":
            raise RuntimeError("model")
        return (SimpleNamespace(model_id="resolved-model"),)
    def isolation(provider):
        events.append("isolation")
        if failure == "isolation":
            raise RuntimeError("isolation")
        return "full-isolation"
    def config(root, provider):
        events.append("config")
        if failure == "config":
            raise RuntimeError("config")
        return {"provider-id": provider, "config": {"option": "value"}}
    monkeypatch.setattr(instances, "resolve_instance_facts", model)
    monkeypatch.setattr(providers_api, "get_provider_execution_isolation_tier", isolation)
    monkeypatch.setattr(providers_api, "get_provider_runtime_config_state", config)


@pytest.mark.parametrize("failure,expected", [("model", ["model"]), ("isolation", ["model", "isolation"]), ("config", ["model", "isolation", "config"])])
def test_model_provider_config_errors_precede_chat_url_validation(tmp_path, monkeypatch, failure, expected):
    events = []
    fact_dependencies(monkeypatch, events, failure)
    with pytest.raises(RuntimeError, match=failure):
        local_dispatch.resolve_local_execution_facts(project_root=tmp_path, selection=selection(), component_profile=None, prompt=prompt(), provider_chat_url="https://chatgpt.com/not-relevant")
    assert events == expected


def test_chat_url_validation_follows_provider_config_and_precedes_digest(tmp_path, monkeypatch):
    events = []
    fact_dependencies(monkeypatch, events)
    digest = Mock(side_effect=AssertionError("digest ran before URL validation"))
    monkeypatch.setattr(execution_context, "compute_agent_runtime_digest", digest)
    with pytest.raises(AudiaGenticError, match="VAL-AGW-151"):
        local_dispatch.resolve_local_execution_facts(project_root=tmp_path, selection=selection(), component_profile=None, prompt=prompt(), provider_chat_url="https://chatgpt.com/not-relevant")
    assert events == ["model", "isolation", "config"]
    digest.assert_not_called()


@pytest.mark.parametrize("instance_ids", [("source-a",), ("source-a", "source-b")])
def test_execution_facts_exact_historical_runtime_digest(tmp_path, monkeypatch, instance_ids):
    events = []
    fact_dependencies(monkeypatch, events)
    selected, rendered = selection(instance_ids=instance_ids), prompt()
    result = local_dispatch.resolve_local_execution_facts(project_root=tmp_path, selection=selected, component_profile="custom", prompt=rendered, provider_chat_url=None)
    payload = {"execution_profile": selected.profile, "provider_config": {"provider-id": "codex", "config": {"option": "value"}}, "component_overlay": {"component-profile": "custom", "prompt-profile-id": "default", "prompt-template-name": "prompt-definition:default", "prompt-template-digest": hashlib.sha256(b"BODY").hexdigest()}}
    expected = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    assert result.runtime_digest == expected
    assert result.isolation_tier == "full-isolation"
    assert result.model_id == ("resolved-model" if len(instance_ids) == 1 else None)
    assert events == (["model"] if len(instance_ids) == 1 else []) + ["isolation", "config"]


def test_ordinary_idle_grace_before_model_and_manifest_after_session(catalog, tmp_path, monkeypatch):
    path, data = catalog
    data["execution_profiles"]["native"]["provider_id"] = "gpt-auto"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    monkeypatch.setattr(profiles, "_gateway_registry", None)
    events = []
    fact_dependencies(monkeypatch, events)
    original_semantics = semantics.resolve_agent_semantics
    def resolve(agent):
        events.append("semantics")
        return original_semantics(agent)
    monkeypatch.setattr(semantics, "resolve_agent_semantics", resolve)
    def reader(root):
        events.append("reader")
        return {}
    def baseline(*args, **kwargs):
        events.append("baseline")
        return {"project": {"name": "canonical"}}
    monkeypatch.setattr(context, "baseline_agent_template_context", baseline)
    original_render = instructions.render_expanded_prompt
    def render(*args, **kwargs):
        events.append("render")
        return original_render(*args, **kwargs)
    monkeypatch.setattr(instructions, "render_expanded_prompt", render)
    original_profile = global_catalog.resolve_global_execution_profile
    def profile(*args):
        events.append("profile")
        return original_profile(*args)
    monkeypatch.setattr(global_catalog, "resolve_global_execution_profile", profile)
    def grace(params):
        events.append("idle")
        return 123
    monkeypatch.setattr(idle_grace, "gpt_idle_grace", grace)
    @contextmanager
    def session(*args, **kwargs):
        events.append("session")
        yield SimpleNamespace(session_id=None, provider_chat_url=None, identity=None)
    monkeypatch.setattr(client_defaults, "select", session)
    original_digest = execution_context.compute_agent_runtime_digest
    def digest(**kwargs):
        events.append("digest")
        return original_digest(**kwargs)
    monkeypatch.setattr(execution_context, "compute_agent_runtime_digest", digest)
    def manifest(envelope, **kwargs):
        events.append("manifest")
        assert kwargs["canonical_root"].display == str(tmp_path)
        assert kwargs["model_id"] == "resolved-model"
        assert kwargs["agent_config_fingerprint"] == original_semantics("reader").composition_fingerprint
        assert envelope.prompt_body == "BODY"
        raise RuntimeError("stop at manifest")
    monkeypatch.setattr(execution_context, "build_manifest", manifest)
    # Preserve ordinary private-wrapper injection seams while using public facts.
    profile_wrapper = Mock(wraps=api._resolve_profile_for_submit)
    isolation_wrapper = Mock(wraps=api._resolve_provider_isolation_tier)
    monkeypatch.setattr(api, "_resolve_profile_for_submit", profile_wrapper)
    monkeypatch.setattr(api, "_resolve_provider_isolation_tier", isolation_wrapper)
    with pytest.raises(RuntimeError, match="stop at manifest"):
        api.submit_execution_request(tmp_path, agent_id="reader", prompt_body="BODY", component_context_reader=reader)
    assert events == ["reader", "baseline", "semantics", "render", "profile", "profile", "idle", "model", "isolation", "config", "digest", "session", "manifest"]
    profile_wrapper.assert_called_once_with(tmp_path, "native")
    isolation_wrapper.assert_called_once_with("gpt-auto")


def test_admission_helpers_import_without_api_queue_sessions_or_runtime():
    script = '''
import importlib.abc
import sys
class Guard(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(("audiagentic.components.agents.gateway.api", "audiagentic.components.agents.gateway.queue", "audiagentic.components.agents.gateway.session", "audiagentic.runtime")):
            raise AssertionError("effect owner imported: " + fullname)
sys.meta_path.insert(0, Guard())
from audiagentic.components.agents.gateway.admission import local_dispatch, semantics
assert local_dispatch.materialize_local_prompt(raw_prompt="raw", semantics=None, template_context={}).text == "raw"
'''
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[3] / "src"))
    result = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
