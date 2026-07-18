from __future__ import annotations

from pathlib import Path

import pytest

from audiagentic.components.providers.services.model_source_config import (
    load_model_sources,
    model_sources_path,
    validate_model_sources,
    write_model_sources,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError


def _local_endpoint(**overrides) -> dict:
    base = {
        "source-class": "local-endpoint",
        "display-name": "Local model",
        "connector": "openai-compatible",
        "base-url": "http://127.0.0.1:1234/v1",
        "api-key-ref": "env:LOCAL_KEY",
        "model-id": "local-model-a",
        "context-window": 131072,
        "max-output-tokens": 4096,
        "capabilities": {"tool-use": True, "reasoning": False, "vision": False},
    }
    base.update(overrides)
    return base


def _remote_account(**overrides) -> dict:
    base = {
        "source-class": "remote-account",
        "display-name": "OpenRouter",
        "connector": "openrouter",
        "base-url": "https://openrouter.ai/api/v1",
        "api-key-ref": "env:OPENROUTER_API_KEY",
        "model-discovery": "list-api",
        "model-filter": {"include": ["anthropic/*"], "exclude": ["*-preview"]},
        "enabled": True,
    }
    base.update(overrides)
    return base


def test_valid_local_endpoint_source_passes() -> None:
    payload = {"contract-version": "v1", "sources": {"qwen-local": _local_endpoint()}}
    assert validate_model_sources(payload) == []


def test_valid_remote_account_source_passes() -> None:
    payload = {"contract-version": "v1", "sources": {"openrouter-main": _remote_account(**{"vendor-id": "openrouter"})}}
    assert validate_model_sources(payload) == []


def test_multiple_sources_of_both_classes_pass() -> None:
    payload = {
        "contract-version": "v1",
        "sources": {
            "local-a": _local_endpoint(),
            "local-b": _local_endpoint(**{"model-id": "local-model-b"}),
            "remote-a": _remote_account(),
        },
    }
    assert validate_model_sources(payload) == []


def test_unknown_source_class_rejected() -> None:
    payload = {
        "contract-version": "v1",
        "sources": {"bad": _local_endpoint(**{"source-class": "vendor-account"})},
    }
    assert validate_model_sources(payload) != []


def test_unknown_model_discovery_rejected() -> None:
    payload = {
        "contract-version": "v1",
        "sources": {"bad": _remote_account(**{"model-discovery": "webhook"})},
    }
    assert validate_model_sources(payload) != []


def test_local_endpoint_requires_model_id() -> None:
    source = _local_endpoint()
    del source["model-id"]
    payload = {"contract-version": "v1", "sources": {"bad": source}}
    assert validate_model_sources(payload) != []


def test_remote_account_does_not_require_model_id() -> None:
    payload = {"contract-version": "v1", "sources": {"ok": _remote_account()}}
    assert validate_model_sources(payload) == []


def test_provider_overrides_accepted() -> None:
    source = _local_endpoint(**{
        "provider-overrides": {"pi": {"api": "openai-completions"}, "opencode": {"provider-id": "audiagentic-local"}},
        "default": True,
    })
    payload = {"contract-version": "v1", "sources": {"a": source}}
    assert validate_model_sources(payload) == []


def test_connector_options_is_free_form() -> None:
    source = _remote_account(**{"connector-options": {"anthropic-version": "2023-06-01", "arbitrary": 123}})
    payload = {"contract-version": "v1", "sources": {"a": source}}
    assert validate_model_sources(payload) == []


def test_missing_file_returns_empty_v1_document(tmp_path: Path) -> None:
    assert load_model_sources(tmp_path) == {"contract-version": "v1", "sources": {}}


def test_write_then_load_roundtrips(tmp_path: Path) -> None:
    payload = {"contract-version": "v1", "sources": {"a": _local_endpoint()}}
    write_model_sources(tmp_path, payload)
    assert model_sources_path(tmp_path).exists()
    assert load_model_sources(tmp_path) == payload


def test_write_rejects_invalid_payload(tmp_path: Path) -> None:
    payload = {"contract-version": "v1", "sources": {"a": {"source-class": "nope", "connector": "openai-compatible"}}}
    with pytest.raises(AudiaGenticError) as exc:
        write_model_sources(tmp_path, payload)
    assert exc.value.code == "VAL-MEP-001"
    assert not model_sources_path(tmp_path).exists()


def test_load_malformed_yaml_raises(tmp_path: Path) -> None:
    path = model_sources_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("sources: [not, a, mapping]\ncontract-version: v1\n", encoding="utf-8")
    with pytest.raises(AudiaGenticError) as exc:
        load_model_sources(tmp_path)
    assert exc.value.code == "VAL-MEP-001"


def test_wrong_contract_version_rejected() -> None:
    payload = {"contract-version": "v2", "sources": {}}
    assert validate_model_sources(payload) != []


def test_additional_top_level_key_rejected() -> None:
    payload = {"contract-version": "v1", "sources": {}, "extra": True}
    assert validate_model_sources(payload) != []
