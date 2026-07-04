from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from audiagentic.components.coding_lsp.lsp_config_api import (
    get_config,
    remove_language,
    set_config,
)
from audiagentic.foundation.features import registry as feature_registry
from audiagentic.foundation.features.base import (
    BindingDescriptor,
    FeatureState,
    ImplementationDescriptor,
    OptionSchema,
)
from audiagentic.foundation.features.state import set_feature_state


def setup_function() -> None:
    feature_registry.clear()


def teardown_function() -> None:
    feature_registry.clear()


def _enable_language(tmp_path: Path, language: str) -> None:
    feature_registry.register(
        BindingDescriptor(
            parent="coding-lsp",
            implementation="ag-lsp",
            feature_kind="language",
            feature=language,
            projection_writer_key="coding-lsp.lsp-json",
        )
    )
    set_feature_state(
        tmp_path,
        "coding-lsp",
        "language",
        language,
        FeatureState(enabled=True),
    )


def test_remove_language_calls_prune_providers(tmp_path: Path) -> None:
    """Removing a language must prune provider configs so stale LSP entries are cleaned up."""
    _enable_language(tmp_path, "python")

    with patch(
        "audiagentic.components.coding_lsp.language_servers_sync.prune_language_servers_from_providers"
    ) as mock_prune:
        mock_prune.return_value = {"ok": True, "pruned": []}
        with patch(
            "audiagentic.components.coding_lsp.lsp_config_api._sync_to_providers"
        ):
            with patch(
                "audiagentic.components.coding_lsp.lsp_config_api._regenerate_lsp_cache"
            ):
                with patch(
                    "audiagentic.components.coding_lsp.lsp_api._session_manager"
                ):
                    result = remove_language(str(tmp_path), "python")

    assert result["ok"] is True
    assert result["language"] == "python"
    mock_prune.assert_called_once_with(tmp_path)


def test_remove_language_returns_error_when_not_configured(tmp_path: Path) -> None:
    result = remove_language(str(tmp_path), "python")
    assert result["ok"] is False
    assert "not configured" in result["error"]


def _register_ag_lsp() -> None:
    feature_registry.register(
        ImplementationDescriptor(
            parent="coding-lsp",
            implementation_id="ag-lsp",
            display_name="AG LSP",
            raw={"default": True},
            options_schema={
                "mutation-enabled": OptionSchema(
                    option_type="boolean",
                    default=False,
                    description="Allow LSP mutation tools",
                ),
            },
        )
    )


def test_get_config_exposes_mutation_enabled_schema(tmp_path: Path) -> None:
    _register_ag_lsp()

    result = get_config(str(tmp_path), "ag-lsp")

    assert result["implementation"] == "ag-lsp"
    assert "mutation-enabled" in result["schema"]
    assert result["config"]["mutation-enabled"] is False
    assert result["is_default"] is True


def test_set_config_persists_mutation_enabled(tmp_path: Path) -> None:
    _register_ag_lsp()

    result = set_config(str(tmp_path), "ag-lsp", {"mutation-enabled": True})
    assert result["ok"] is True
    assert result["config"]["mutation-enabled"] is True

    fetched = get_config(str(tmp_path), "ag-lsp")
    assert fetched["config"]["mutation-enabled"] is True


def test_set_config_rejects_unknown_option(tmp_path: Path) -> None:
    _register_ag_lsp()

    result = set_config(str(tmp_path), "ag-lsp", {"bogus": "x"})
    assert result["ok"] is False
    assert "unknown option" in result["error"]


def test_set_config_rejects_wrong_type(tmp_path: Path) -> None:
    _register_ag_lsp()

    result = set_config(str(tmp_path), "ag-lsp", {"mutation-enabled": "not-a-bool"})
    assert result["ok"] is False
    assert "invalid value" in result["error"]


def test_set_config_unknown_implementation(tmp_path: Path) -> None:
    result = set_config(str(tmp_path), "no-such-implementation", {"x": 1})
    assert result["ok"] is False
    assert "unknown LSP implementation" in result["error"]
