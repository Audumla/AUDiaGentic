from __future__ import annotations

import inspect
from types import SimpleNamespace

from audiagentic.components.providers import providers_api
from audiagentic.components.providers.providers_mcp import build_server
from audiagentic.components.providers.services.models import resolve_model_selection
from audiagentic.components.providers.services.provider_catalog import (
    build_model_catalog,
    validate_model_catalog,
)
from audiagentic.foundation.components.registry import get_mcp_server_declaration
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


def test_list_provider_models_has_no_refresh_mode() -> None:
    signature = inspect.signature(providers_api.list_provider_models)

    assert tuple(signature.parameters) == ("project_root", "provider_id")


def test_list_provider_models_does_not_fetch_catalog(monkeypatch, tmp_path) -> None:
    from audiagentic.components.providers.descriptors import registry
    from audiagentic.components.providers.services import catalog

    monkeypatch.setattr(
        registry,
        "all_descriptors",
        lambda: {"fixture": SimpleNamespace(fetch_catalog_fn=lambda _: [])},
    )

    def _unexpected_fetch(*args, **kwargs):
        raise AssertionError("query attempted remote catalog fetch")

    monkeypatch.setattr(catalog, "fetch_provider_catalog", _unexpected_fetch)

    result = providers_api.list_provider_models(tmp_path, "fixture")

    assert result["reason"] == "no-catalog-found"
    assert not tmp_path.exists() or not any(tmp_path.rglob("*"))


def test_mcp_list_provider_models_has_no_refresh_argument() -> None:
    server = build_server()
    tool = server._tool_manager._tools["list_provider_models"]

    assert tool.parameters["properties"] == {
        "provider_id": {"title": "Provider Id", "type": "string"}
    }
    assert tool.parameters["required"] == ["provider_id"]


def test_providers_mcp_descriptor_names_only_real_tools() -> None:
    declaration = get_mcp_server_declaration("providers", "ag-providers-mgmt")
    server = build_server()

    assert set(declaration.direct_tools) == set(server._tool_manager._tools)
    assert set(declaration.tool_descriptions) == set(declaration.direct_tools)


def test_model_mcp_surface_is_audiagentic_centric() -> None:
    tools = set(build_server()._tool_manager._tools)

    assert {
        "list_model_inventory",
        "refresh_model_source_catalog",
        "model_vendor_set_enabled",
        "apply_model_sources",
    } <= tools
    assert "manage_model_projection" not in tools


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
