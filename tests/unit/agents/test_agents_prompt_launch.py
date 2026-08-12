"""Unit tests for execution profile resolution in prompt_launch."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from audiagentic.components.agent_jobs.prompt_launch import _resolve_agent_provider_model
from audiagentic.components.agents.models import execution_profile_api as agents_api
from audiagentic.foundation.contracts.errors import AudiaGenticError


def _make_request(execution_profile_id=None, **kwargs) -> dict:
    base = {
        "source": {
            "provider-id": "local-openai",
        },
    }
    if execution_profile_id is not None:
        base["execution-profile-id"] = execution_profile_id
    base.update(kwargs)
    return base


def _setup_profiles(tmp_path: Path):
    agents_api.create_execution_profile(
        tmp_path,
        {
            "profile_id": "test-profile",
            "provider_id": "anthropic",
            "instances": ["claude-3"],
            "model_alias": "claude",
            "params": {"temperature": 0.5},
        },
    )


def _setup_default_profile(tmp_path: Path):
    agents_api.create_execution_profile(
        tmp_path,
        {
            "profile_id": "default",
            "provider_id": "local-openai",
            "instances": ["gpt-4o"],
            "is_default": True,
        },
    )


def _patch_enabled(enabled=True):
    return patch(
        "audiagentic.components.agent_jobs.prompt_launch.is_provider_enabled",
        return_value=enabled,
    )


# ---------------------------------------------------------------------------
# execution-profile-id takes precedence
# ---------------------------------------------------------------------------

def test_resolve_execution_profile_id_overrides_provider(tmp_path):
    _setup_profiles(tmp_path)
    request = _make_request(execution_profile_id="test-profile")
    with _patch_enabled():
        provider_id, model_id, model_alias = _resolve_agent_provider_model(tmp_path, request)
    assert provider_id == "anthropic"
    assert model_id == "claude-3"
    assert model_alias == "claude"


def test_resolve_execution_profile_id_overrides_explicit_provider(tmp_path):
    _setup_profiles(tmp_path)
    request = _make_request(execution_profile_id="test-profile")
    request["source"]["provider-id"] = "local-openai"
    request["source"]["model-id"] = "gpt-4o"
    with _patch_enabled():
        provider_id, model_id, model_alias = _resolve_agent_provider_model(tmp_path, request)
    assert provider_id == "anthropic"
    assert model_id == "claude-3"


# ---------------------------------------------------------------------------
# explicit provider/model falls back when no execution-profile-id
# ---------------------------------------------------------------------------

def test_resolve_explicit_provider_model_without_profile(tmp_path):
    request = _make_request()
    request["source"]["provider-id"] = "local-openai"
    request["source"]["model-id"] = "gpt-4o"
    provider_id, model_id, model_alias = _resolve_agent_provider_model(tmp_path, request)
    assert provider_id == "local-openai"
    assert model_id == "gpt-4o"
    assert model_alias is None


def test_resolve_explicit_provider_only(tmp_path):
    request = _make_request()
    request["source"]["provider-id"] = "local-openai"
    provider_id, model_id, model_alias = _resolve_agent_provider_model(tmp_path, request)
    assert provider_id == "local-openai"


# ---------------------------------------------------------------------------
# default profile fallback
# ---------------------------------------------------------------------------

def test_resolve_default_execution_profile_when_no_explicit(tmp_path):
    _setup_default_profile(tmp_path)
    request = {}
    with _patch_enabled():
        provider_id, model_id, model_alias = _resolve_agent_provider_model(tmp_path, request)
    assert provider_id == "local-openai"
    assert model_id == "gpt-4o"


def test_resolve_no_default_no_explicit_raises_con_agj_001(tmp_path):
    request = {}
    with pytest.raises(AudiaGenticError) as exc_info:
        _resolve_agent_provider_model(tmp_path, request)
    assert exc_info.value.code == "CON-AGJ-001"


# ---------------------------------------------------------------------------
# disabled provider check
# ---------------------------------------------------------------------------

def test_resolve_execution_profile_disabled_provider_raises_con_agj_002(tmp_path):
    _setup_profiles(tmp_path)
    request = _make_request(execution_profile_id="test-profile")
    with _patch_enabled(enabled=False):
        with pytest.raises(AudiaGenticError) as exc_info:
            _resolve_agent_provider_model(tmp_path, request)
    assert exc_info.value.code == "CON-AGJ-002"
    assert exc_info.value.details["profile_id"] == "test-profile"
    assert exc_info.value.details["provider_id"] == "anthropic"


def test_resolve_default_execution_profile_disabled_provider_raises_con_agj_002(tmp_path):
    _setup_default_profile(tmp_path)
    request = {}
    with _patch_enabled(enabled=False):
        with pytest.raises(AudiaGenticError) as exc_info:
            _resolve_agent_provider_model(tmp_path, request)
    assert exc_info.value.code == "CON-AGJ-002"


def test_resolve_execution_profile_enabled_provider_succeeds(tmp_path):
    _setup_profiles(tmp_path)
    request = _make_request(execution_profile_id="test-profile")
    with _patch_enabled():
        provider_id, model_id, model_alias = _resolve_agent_provider_model(tmp_path, request)
    assert provider_id == "anthropic"
    assert model_id == "claude-3"


# ---------------------------------------------------------------------------
# profile not found propagates
# ---------------------------------------------------------------------------

def test_resolve_unknown_execution_profile_raises_res_exp_001(tmp_path):
    request = _make_request(execution_profile_id="nonexistent")
    with pytest.raises(AudiaGenticError) as exc_info:
        _resolve_agent_provider_model(tmp_path, request)
    assert exc_info.value.code == "RES-EXP-001"


# ---------------------------------------------------------------------------
# precedence summary test
# ---------------------------------------------------------------------------

def test_precedence_execution_profile_id_over_default(tmp_path):
    _setup_default_profile(tmp_path)
    _setup_profiles(tmp_path)
    request = _make_request(execution_profile_id="test-profile")
    with _patch_enabled():
        provider_id, model_id, _ = _resolve_agent_provider_model(tmp_path, request)
    assert provider_id == "anthropic"
    assert model_id == "claude-3"


def test_precedence_explicit_over_default(tmp_path):
    _setup_default_profile(tmp_path)
    request = _make_request()
    request["source"]["provider-id"] = "custom-provider"
    provider_id, _, _ = _resolve_agent_provider_model(tmp_path, request)
    assert provider_id == "custom-provider"


def test_precedence_default_when_nothing_else(tmp_path):
    _setup_default_profile(tmp_path)
    request = {}
    with _patch_enabled():
        provider_id, model_id, _ = _resolve_agent_provider_model(tmp_path, request)
    assert provider_id == "local-openai"
    assert model_id == "gpt-4o"
