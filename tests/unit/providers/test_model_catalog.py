from __future__ import annotations

from types import SimpleNamespace

from audiagentic.components.providers import providers_api
from audiagentic.components.providers.services.models import resolve_model_selection
from audiagentic.components.providers.services.provider_catalog import (
    build_model_catalog,
    validate_model_catalog,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError


def test_list_provider_models_distinguishes_unsupported_catalog(monkeypatch, tmp_path) -> None:
    from audiagentic.components.providers.descriptors import registry

    monkeypatch.setattr(
        registry, "all_descriptors", lambda: {"fixture": SimpleNamespace(fetch_catalog_fn=None)}
    )

    result = providers_api.list_provider_models(tmp_path, "fixture")

    assert result == {
        "provider_id": "fixture",
        "models": [],
        "ok": True,
        "reason": "no-catalog-support",
        "catalog_present": False,
        "stale": False,
    }


def test_build_model_catalog_validates_shape() -> None:
    payload = build_model_catalog(
        provider_id="codex",
        models=[
            {
                "model-id": "gpt-5.4-mini",
                "display-name": "GPT-5.4 Mini",
                "status": "active",
                "supports-structured-output": True,
                "context-window": 200000,
            }
        ],
        fetched_at="2026-03-30T00:00:00Z",
        source="cli",
    )
    assert validate_model_catalog(payload) == []


def test_resolve_model_selection_prefers_alias_and_catalog() -> None:
    selection = resolve_model_selection(
        provider_id="codex",
        provider_config={
            "default-model": "gpt-5.4-mini",
            "model-aliases": {"fast": "gpt-5.4-mini"},
        },
        job_request={"model-alias": "fast"},
        catalog={
            "contract-version": "v1",
            "provider-id": "codex",
            "fetched-at": "2026-03-30T00:00:00Z",
            "source": "cli",
            "models": [
                {
                    "model-id": "gpt-5.4-mini",
                    "status": "active",
                    "supports-structured-output": True,
                    "context-window": 200000,
                }
            ],
        },
    )
    assert selection["model-id"] == "gpt-5.4-mini"
    assert selection["resolved-from"] == "alias"


def test_resolve_model_selection_rejects_missing_alias() -> None:
    try:
        resolve_model_selection(
            provider_id="codex",
            provider_config={"model-aliases": {}},
            job_request={"model-alias": "fast"},
            catalog=None,
        )
    except AudiaGenticError as exc:
        assert exc.kind == "providers"
    else:
        raise AssertionError("expected validation error")
