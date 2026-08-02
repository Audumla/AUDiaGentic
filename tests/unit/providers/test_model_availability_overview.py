"""MO20 — Cross-harness model availability overview tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from audiagentic.components.providers.services.catalog.overview import (
    ModelAvailabilityOverview,
    ProviderOverviewRow,
    SourceOverviewRow,
    build_model_availability_overview,
)


def test_overview_returns_typed_dict(tmp_path: Path) -> None:
    """The overview function must return a dict with the expected top-level keys."""
    result = build_model_availability_overview(tmp_path)

    assert isinstance(result, ModelAvailabilityOverview)
    assert hasattr(result, "providers")
    assert hasattr(result, "sources")
    assert hasattr(result, "materialized")

    # All sub-structures are lists
    assert isinstance(result.providers, list)
    assert isinstance(result.sources, list)
    assert isinstance(result.materialized, list)


def test_overview_provider_row_shape(tmp_path: Path) -> None:
    """Each provider row must have the required fields."""
    result = build_model_availability_overview(tmp_path)

    for row in result.providers:
        assert hasattr(row, "provider_id")
        assert hasattr(row, "enabled")
        assert hasattr(row, "installed")
        assert hasattr(row, "model_count")
        assert hasattr(row, "models_stale")
        assert hasattr(row, "managed_model_count")
        assert hasattr(row, "errors")


def test_overview_source_row_shape(tmp_path: Path) -> None:
    """Each source row must have the required fields."""
    result = build_model_availability_overview(tmp_path)

    for row in result.sources:
        assert hasattr(row, "source_id")
        assert hasattr(row, "enabled")
        assert hasattr(row, "connector")
        assert hasattr(row, "discovery_mode")
        # model_count, freshness, stale are optional/default fields
        if hasattr(row, "model_count"):
            pass  # may or may not be present depending on source data


def test_overview_materialized_row_shape(tmp_path: Path) -> None:
    """Each materialized row must have the required fields."""
    result = build_model_availability_overview(tmp_path)

    for row in result.materialized:
        assert hasattr(row, "provider_id")
        assert hasattr(row, "source_id")
        assert hasattr(row, "managed_id_count")


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

    def _explode(*args, **kwargs):
        raise AssertionError("model_availability_overview performed a network call")

    with patch(
        "audiagentic.components.providers.services.catalog.source_catalog._http_get_json",
        _explode,
    ):
        # Should complete without hitting the network
        result = build_model_availability_overview(tmp_path)

    assert isinstance(result, ModelAvailabilityOverview)
    assert hasattr(result, "providers")
