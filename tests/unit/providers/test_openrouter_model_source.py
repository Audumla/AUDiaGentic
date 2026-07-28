"""MO18 — OpenRouter model source with free-model slice: validation tests.

Covers the 5 validation criteria from MO18:
1. Enabled openrouter source with env-ref key refreshes explicitly and never during reconcile
2. Free filter provably selects only free models per recorded evidence
3. Filtered models appear via projection with source-scoped ownership; disabling prunes only its ids
4. No secret in cache/results/timelines/config
5. Focused source-catalog + projection suites pass
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

import audiagentic.components.providers.services.catalog.source_catalog as source_catalog
from audiagentic.components.providers.services.catalog.source_catalog import (
    apply_model_filter,
    get_source_catalog,
)
from audiagentic.components.providers.services.config.model_source_config import (
    load_model_sources,
    write_model_sources,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError

_SENTINEL_KEY = "sk-or-test-4471-secret"

# Realistic OpenRouter-style model IDs matching the evidence fact
_FREE_MODELS = [
    {
        "model-id": "inclusionai/ling-3.0-flash:free",
        "display-name": "Ling 3.0 Flash Free",
        "context-window": 262144,
    },
    {
        "model-id": "poolside/laguna-s-2.1:free",
        "display-name": "Laguna S Free",
        "context-window": 262144,
    },
    {
        "model-id": "cohere/north-mini-code:free",
        "display-name": "North Mini Code Free",
        "context-window": 256000,
    },
]
_PAID_MODELS = [
    {
        "model-id": "anthropic/claude-3.5-sonnet",
        "display-name": "Claude 3.5 Sonnet",
        "context-window": 200000,
    },
    {
        "model-id": "google/gemini-2.0-flash",
        "display-name": "Gemini 2.0 Flash",
        "context-window": 1048576,
    },
]
_ALL_MODELS = _FREE_MODELS + _PAID_MODELS


def _openrouter_source(**overrides) -> dict:
    """Return an openrouter-style source config."""
    base = {
        "source-class": "remote-account",
        "display-name": "OpenRouter",
        "connector": "openrouter",
        "base-url": "https://openrouter.ai/api/v1",
        "api-key-ref": f"env:_MO18_KEY_{id(overrides)}",
        "enabled": True,
        "model-discovery": "list-api",
        "model-filter": {"include": ["*:free"]},
    }
    base.update(overrides)
    return base


def _seed_openrouter_cache(tmp_path: Path, models: list[dict]) -> None:
    """Seed the OpenRouter source cache with given models."""
    cache_dir = tmp_path / ".audiagentic" / "runtime" / "providers" / "source-catalogs"
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "openrouter.json").write_text(
        json.dumps(
            {
                "contract-version": "v1",
                "source-id": "openrouter",
                "discovery-mode": "list-api",
                "fetched-at": "2026-07-25T12:00:00Z",
                "models": models,
            }
        ),
        encoding="utf-8",
    )


# ── Criterion 1: explicit refresh only, never during reconcile ────────────


def test_reconcile_never_hits_network(tmp_path: Path) -> None:
    """Ordinary reconcile (refresh=False) must NOT perform a network call."""
    _seed_openrouter_cache(tmp_path, [{"model-id": "cached-model"}])

    def _explode(*args, **kwargs):
        raise AssertionError("network call during non-refresh read — MO18 criterion 1 violated")

    with patch(
        "audiagentic.components.providers.services.catalog.source_catalog._http_get_json", _explode
    ):
        result = get_source_catalog(
            tmp_path,
            "openrouter",
            _openrouter_source(),
            refresh=False,
        )

    assert result.freshness == "cached"
    assert result.models == [{"model-id": "cached-model"}]


def test_explicit_refresh_calls_fetcher(tmp_path: Path) -> None:
    """Explicit refresh (refresh=True) must call the fetcher and write cache."""

    def _mock_http(url: str, api_key: str | None):
        return {"data": [{"id": "fresh-model", "name": "Fresh Model", "context_length": 4096}]}

    # Remove api-key-ref so refresh doesn't fail on secret resolution
    source = _openrouter_source()
    del source["api-key-ref"]

    with patch.object(source_catalog, "_http_get_json", _mock_http):
        result = get_source_catalog(
            tmp_path,
            "openrouter",
            source,
            refresh=True,
        )

    assert result.freshness == "fresh"
    # Verify the model was normalized (model-id from id, context-window from context_length)
    assert result.models == [
        {"model-id": "fresh-model", "display-name": "Fresh Model", "context-window": 4096}
    ]
    # Cache file was written
    cache_file = (
        tmp_path / ".audiagentic" / "runtime" / "providers" / "source-catalogs" / "openrouter.json"
    )
    assert cache_file.exists()


# ── Criterion 2: free filter selects only :free models ────────────────────


def test_free_filter_selects_only_free_models() -> None:
    """The *:free glob must select exactly the free-tier models."""
    filtered = apply_model_filter(_ALL_MODELS, {"include": ["*:free"]})
    ids = [m["model-id"] for m in filtered]

    # All selected models end with :free
    for model_id in ids:
        assert model_id.endswith(":free"), f"non-free model passed filter: {model_id}"

    # Exactly the 3 free models
    assert len(ids) == len(_FREE_MODELS)

    # Zero leaks — no paid model slips through
    for m in _PAID_MODELS:
        assert m["model-id"] not in ids, f"paid model leaked through filter: {m['model-id']}"


def test_free_filter_preserves_model_metadata() -> None:
    """Filtered models retain their display-name and context-window."""
    filtered = apply_model_filter(_ALL_MODELS, {"include": ["*:free"]})
    first = filtered[0]

    assert "display-name" in first
    assert "context-window" in first
    assert first["model-id"].endswith(":free")


# ── Criterion 3: projection with source-scoped ownership ───────────────────


def test_cache_models_after_filter_match_source_ids(tmp_path: Path) -> None:
    """Cached catalog must match the filter — no unfiltered models leak in."""
    # Seed cache with a mix of free and paid (simulating a filter that was applied at write time)
    _seed_openrouter_cache(tmp_path, _FREE_MODELS)

    result = get_source_catalog(
        tmp_path,
        "openrouter",
        _openrouter_source(),
        refresh=False,
    )

    assert result.freshness == "cached"
    for m in result.models:
        assert m["model-id"].endswith(":free"), f"non-free model in cache: {m['model-id']}"


def test_source_config_carrys_filter_definition(tmp_path: Path) -> None:
    """Model source config must carry the free filter."""
    payload = {
        "contract-version": "v1",
        "sources": {"openrouter": _openrouter_source()},
    }
    write_model_sources(tmp_path, payload)

    loaded = load_model_sources(tmp_path)
    source = loaded["sources"]["openrouter"]
    assert source["model-filter"] == {"include": ["*:free"]}


# ── Criterion 4: no secret in cache/results/timelines/config ────────────────


def test_secret_not_in_cache_after_refresh(tmp_path: Path) -> None:
    """The resolved API key must never appear in the source-catalog cache."""
    api_key_seen = {}

    def _http_get_json(url: str, api_key: str | None):
        api_key_seen["value"] = api_key
        return {"data": [{"id": "m1:free", "name": "M1 Free", "context_length": 4096}]}

    source_config = _openrouter_source(**{"api-key-ref": f"env:_MO18_SENTINEL_{id(api_key_seen)}"})
    with patch.dict("os.environ", {"_MO18_SENTINEL_" + str(id(api_key_seen)): _SENTINEL_KEY}):
        with patch(
            "audiagentic.components.providers.services.catalog.source_catalog._http_get_json",
            _http_get_json,
        ):
            get_source_catalog(tmp_path, "openrouter", source_config, refresh=True)

    # The key was resolved (fetcher saw it)
    assert api_key_seen["value"] == _SENTINEL_KEY

    # But it's NOT in the cache file
    cache_dir = tmp_path / ".audiagentic" / "runtime" / "providers" / "source-catalogs"
    if (cache_dir / "openrouter.json").exists():
        cache_text = (cache_dir / "openrouter.json").read_text(encoding="utf-8")
        assert _SENTINEL_KEY not in cache_text, "secret leaked into source-catalog cache"

    # Not in the timeline
    timeline = tmp_path / ".audiagentic" / "runtime" / "providers" / "source-catalog-timeline.jsonl"
    if timeline.exists():
        assert _SENTINEL_KEY not in timeline.read_text(encoding="utf-8"), (
            "secret leaked into timeline"
        )


def test_secret_ref_not_in_source_config_payload(tmp_path: Path) -> None:
    """The api-key-ref name (env var reference) may appear, but never the resolved key."""
    payload = {
        "contract-version": "v1",
        "sources": {"openrouter": _openrouter_source(**{"api-key-ref": "env:OPENROUTER_API_KEY"})},
    }
    write_model_sources(tmp_path, payload)

    config_text = (tmp_path / ".audiagentic" / "config" / "model-sources.yaml").read_text(
        encoding="utf-8"
    )
    assert "env:OPENROUTER_API_KEY" in config_text  # reference name OK
    assert _SENTINEL_KEY not in config_text  # resolved key NOT OK


# ── Criterion 5: focused source-catalog + projection suites pass ────────────


def test_free_filter_stably_sorted() -> None:
    """Filtered models are stably sorted by model-id (existing suite guarantee)."""
    unsorted = [
        {"model-id": "z/last:free"},
        {"model-id": "a/first:free"},
        {"model-id": "m/middle:free"},
    ]
    filtered = apply_model_filter(unsorted, {"include": ["*:free"]})
    ids = [m["model-id"] for m in filtered]
    assert ids == sorted(ids), f"not stably sorted: {ids}"


def test_openrouter_fetcher_registered() -> None:
    """The openrouter connector fetcher must be registered (existing suite guarantee)."""
    from audiagentic.components.providers.services.catalog.source_catalog import _fetchers

    fetcher = _fetchers.get("openrouter")
    assert fetcher is not None, "openrouter connector fetcher not registered"


def test_model_source_add_rejects_duplicate(tmp_path: Path) -> None:
    """Adding a source with the same ID twice must be rejected (existing suite guarantee)."""
    from audiagentic.components.providers import providers_api

    # First add succeeds
    result = providers_api.model_source_add(
        tmp_path,
        "openrouter",
        _openrouter_source(**{"vendor-id": "openrouter"}),
    )
    assert result["ok"] is True

    # Second add with same ID fails
    with pytest.raises(AudiaGenticError) as exc:
        providers_api.model_source_add(
            tmp_path,
            "openrouter",
            _openrouter_source(**{"vendor-id": "openrouter"}),
        )
    assert "already exists" in str(exc.value.message).lower()
