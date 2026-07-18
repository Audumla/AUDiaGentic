"""Public providers API boundary tests (MA16)."""

from __future__ import annotations

import asyncio

from audiagentic.components.providers import providers_api


def test_public_api_does_not_export_recipe_construction_or_lifecycle() -> None:
    """Requesters use provider operations, never recipe implementation types."""
    forbidden = {
        "ProviderCapabilityRecipe",
        "ProviderRecipeKind",
        "ProviderRecipeRegistry",
        "ProviderRecipeResult",
    }

    assert forbidden.isdisjoint(providers_api.__all__)
    assert all(not hasattr(providers_api, name) for name in forbidden)


def test_hindsight_family_contracts_are_public_exports() -> None:
    required = {
        "ManagedHooksEntry",
        "ManagedHooksRequest",
        "ManagedHooksResult",
        "ManagedMcpRequest",
        "ManagedMcpResult",
        "PluginEntryRequest",
        "PluginEntryResult",
        "CliLifecycleRequest",
        "CliLifecycleResult",
        "ModelProjectionEntry",
        "ModelProjectionRequest",
        "ModelProjectionResult",
        "list_provider_descriptors",
        "list_providers",
        "manage_hook_entries",
        "manage_mcp_entries",
        "manage_plugin_entry",
        "manage_model_projection",
    }

    assert required <= set(providers_api.__all__)


def test_prompt_launch_operations_are_public_exports() -> None:
    """MA17 keeps prompt parsing and launch semantics off provider internals."""
    required = {
        "list_canonical_provider_ids",
        "get_prompt_syntax_defaults",
        "get_provider_prompt_settings_profile",
        "is_provider_enabled_for_launch",
        "resolve_launch_model",
        "load_packaged_prompt_template",
        "execute_provider_review_turn",
    }

    assert required <= set(providers_api.__all__)


def test_superseded_model_projection_routes_are_not_public() -> None:
    forbidden = {
        "sync_provider_models",
        "list_provider_models_config",
        "reload_provider_models",
    }

    assert forbidden.isdisjoint(providers_api.__all__)
    assert all(not hasattr(providers_api, name) for name in forbidden)


def test_cli_lifecycle_public_operation_returns_typed_result(monkeypatch, tmp_path) -> None:
    from audiagentic.components.providers.providers_api import CliLifecycleResult

    class _Registry:
        def dispatch(self, *args, **kwargs):
            return {"ok": True, "supported": True, "state": "installed"}

    monkeypatch.setattr(
        "audiagentic.components.providers.services.automation_registry.build_automation_registry",
        lambda project_root: _Registry(),
    )

    result = asyncio.run(
        providers_api.manage_cli_lifecycle(tmp_path, "codex", mode="status")
    )

    assert isinstance(result, CliLifecycleResult)
    assert result.state == "installed"
