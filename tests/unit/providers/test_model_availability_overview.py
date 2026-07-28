"""MO20 — Cross-harness model availability overview tests."""

from __future__ import annotations

from pathlib import Path

from audiagentic.components.providers import providers_api
from audiagentic.components.providers.services.catalog.overview import (
    ModelAvailabilityOverview,
    ProviderOverviewRow,
    SourceOverviewRow,
)


def test_overview_returns_typed_dict(tmp_path: Path) -> None:
    """The overview function must return a dict with the expected top-level keys."""
    result = providers_api.model_availability_overview(tmp_path)

    assert isinstance(result, dict)
    assert "providers" in result
    assert "sources" in result
    assert "materialized" in result

    # All sub-structures are lists
    assert isinstance(result["providers"], list)
    assert isinstance(result["sources"], list)
    assert isinstance(result["materialized"], list)


def test_overview_provider_row_shape(tmp_path: Path) -> None:
    """Each provider row must have the required fields."""
    result = providers_api.model_availability_overview(tmp_path)

    for row in result.get("providers", []):
        assert "provider_id" in row
        assert "enabled" in row
        assert "installed" in row
        assert "model_count" in row
        assert "models_stale" in row
        assert "managed_model_count" in row
        assert "errors" in row


def test_overview_source_row_shape(tmp_path: Path) -> None:
    """Each source row must have the required fields."""
    result = providers_api.model_availability_overview(tmp_path)

    for row in result.get("sources", []):
        assert "source_id" in row
        assert "enabled" in row
        assert "connector" in row
        assert "discovery_mode" in row
        assert "model_count" in row
        assert "freshness" in row
        assert "stale" in row


def test_overview_materialized_row_shape(tmp_path: Path) -> None:
    """Each materialized row must have the required fields."""
    result = providers_api.model_availability_overview(tmp_path)

    for row in result.get("materialized", []):
        assert "provider_id" in row
        assert "source_id" in row
        assert "managed_id_count" in row


def test_dataclass_to_dict(tmp_path: Path) -> None:
    """The dataclass to_dict must produce the expected shape."""
    overview = ModelAvailabilityOverview(
        providers=[
            ProviderOverviewRow(
                provider_id="opencode",
                enabled=True,
                installed=True,
                model_count=5,
                models_stale=False,
                managed_model_count=3,
            )
        ],
        sources=[
            SourceOverviewRow(
                source_id="openrouter",
                display_name="OpenRouter",
                enabled=True,
                connector="openrouter",
                discovery_mode="list-api",
                filter_include=["*:free"],
                model_count=15,
                freshness="cached",
            )
        ],
        materialized=[],
    )

    d = overview.to_dict()

    assert len(d["providers"]) == 1
    assert d["providers"][0]["provider_id"] == "opencode"
    assert d["providers"][0]["model_count"] == 5
    assert len(d["sources"]) == 1
    assert d["sources"][0]["source_id"] == "openrouter"
    assert d["sources"][0]["filter_include"] == ["*:free"]
    assert len(d["materialized"]) == 0


def test_no_network_calls(tmp_path: Path) -> None:
    """The overview must not perform network calls — all cached data only."""
    # Patch the HTTP call to explode if invoked
    from unittest.mock import patch

    def _explode(*args, **kwargs):
        raise AssertionError("model_availability_overview performed a network call")

    with patch(
        "audiagentic.components.providers.services.catalog.source_catalog._http_get_json",
        _explode,
    ):
        # Should complete without hitting the network
        result = providers_api.model_availability_overview(tmp_path)

    assert isinstance(result, dict)
    assert "providers" in result
