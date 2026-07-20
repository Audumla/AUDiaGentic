"""Unit tests for the OpenCode isolated-worker execution environment builder.

RV739 follow-up: a project whose config declares no providers must fail
loudly instead of silently falling back to the machine's global OpenCode
whitelist (see the 2026-07-19 SH07 batch incident notes).
"""
from __future__ import annotations

import json

import pytest

from audiagentic.components.providers.adapters.opencode.execution_environment import (
    build_execution_environment,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError


def test_missing_provider_map_raises_instead_of_falling_back_to_global_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENCODE_CONFIG_CONTENT", json.dumps({}))
    with pytest.raises(AudiaGenticError) as captured:
        build_execution_environment(model_id="model-a")
    assert captured.value.code == "CFG-OPENC-002"


def test_empty_provider_map_raises_instead_of_falling_back_to_global_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENCODE_CONFIG_CONTENT", json.dumps({"provider": {}}))
    with pytest.raises(AudiaGenticError) as captured:
        build_execution_environment(model_id="model-a")
    assert captured.value.code == "CFG-OPENC-002"


def test_non_dict_provider_field_raises_instead_of_falling_back_to_global_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENCODE_CONFIG_CONTENT", json.dumps({"provider": "not-a-dict"}))
    with pytest.raises(AudiaGenticError) as captured:
        build_execution_environment(model_id="model-a")
    assert captured.value.code == "CFG-OPENC-002"


def test_declared_providers_are_all_whitelisted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "OPENCODE_CONFIG_CONTENT",
        json.dumps({"provider": {"audiagentic": {}, "anthropic": {}}}),
    )
    result = build_execution_environment(model_id="model-a")
    doc = json.loads(result["OPENCODE_CONFIG_CONTENT"])
    assert set(doc["enabled_providers"]) == {"audiagentic", "anthropic"}
    assert doc["model"] == "model-a"
