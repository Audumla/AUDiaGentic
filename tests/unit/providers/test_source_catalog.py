"""MO12 normalized model-source catalog cache tests."""

from __future__ import annotations

import json
import urllib.error
from pathlib import Path

import pytest

from audiagentic.components.providers.services.catalog import source_catalog
from audiagentic.components.providers.services.catalog.source_catalog import (
    SourceCatalogResult,
    apply_model_filter,
    classify_remote_failure,
    get_source_catalog,
    register_catalog_fetcher,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError

_SENTINEL_KEY = "sekrit-catalog-key-4471"


def _source(**overrides) -> dict:
    base = {
        "source-class": "remote-account",
        "connector": "openai-compatible",
        "base-url": "http://127.0.0.1:9/v1",
        "model-discovery": "list-api",
    }
    base.update(overrides)
    return base


def _cache_file(tmp_path: Path, source_id: str) -> Path:
    return (
        tmp_path
        / ".audiagentic"
        / "runtime"
        / "providers"
        / "source-catalogs"
        / f"{source_id}.json"
    )


def _seed_cache(tmp_path: Path, source_id: str, models: list[dict]) -> None:
    path = _cache_file(tmp_path, source_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "contract-version": "v1",
                "source-id": source_id,
                "discovery-mode": "list-api",
                "fetched-at": "2026-07-12T00:00:00Z",
                "models": models,
            }
        ),
        encoding="utf-8",
    )


# --- result shapes per discovery mode ------------------------------------------


def test_none_discovery_returns_missing_shape(tmp_path: Path) -> None:
    result = get_source_catalog(tmp_path, "src", _source(**{"model-discovery": "none"}))
    assert isinstance(result, SourceCatalogResult)
    assert result.discovery_mode == "none"
    assert result.freshness == "missing"
    assert result.models == []
    assert result.failure_class is None


def test_list_api_without_cache_or_refresh_is_missing(tmp_path: Path) -> None:
    result = get_source_catalog(tmp_path, "src", _source())
    assert result.freshness == "missing"
    assert "refresh" in (result.action_needed or "")


def test_list_api_reads_cache_without_network(tmp_path: Path, monkeypatch) -> None:
    """Ordinary reconcile performs no network call (MO12 validation 7)."""
    _seed_cache(tmp_path, "src", [{"model-id": "m1"}])

    def _explode(*args, **kwargs):  # any fetcher invocation is a failure
        raise AssertionError("network call during non-refresh read")

    monkeypatch.setattr(source_catalog, "_http_get_json", _explode)
    result = get_source_catalog(tmp_path, "src", _source(), refresh=False)
    assert result.freshness == "cached"
    assert result.models == [{"model-id": "m1"}]
    assert result.stale is False


def test_static_catalog_loads_and_validates_data_file(tmp_path: Path, monkeypatch) -> None:
    catalog_dir = tmp_path / "config" / "model-catalogs"
    catalog_dir.mkdir(parents=True)
    (catalog_dir / "anthropic-account.yaml").write_text(
        "contract-version: v1\n"
        "models:\n"
        "  - model-id: claude-x\n"
        "    display-name: Claude X\n"
        "    context-window: 200000\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        source_catalog, "get_package_providers_config_dir", lambda: tmp_path / "config"
    )
    result = get_source_catalog(
        tmp_path, "anthropic-account", _source(**{"model-discovery": "static-catalog"})
    )
    assert result.freshness == "fresh"
    assert result.models[0]["model-id"] == "claude-x"


def test_static_catalog_invalid_data_file_is_contract_failure(tmp_path: Path, monkeypatch) -> None:
    catalog_dir = tmp_path / "config" / "model-catalogs"
    catalog_dir.mkdir(parents=True)
    (catalog_dir / "bad.yaml").write_text(
        "contract-version: v1\nmodels:\n  - display-name: no id\n", encoding="utf-8"
    )
    monkeypatch.setattr(
        source_catalog, "get_package_providers_config_dir", lambda: tmp_path / "config"
    )
    with pytest.raises(AudiaGenticError) as exc:
        get_source_catalog(tmp_path, "bad", _source(**{"model-discovery": "static-catalog"}))
    assert exc.value.code == "CON-SRCCAT-001"


def test_static_catalog_missing_file_is_contract_failure(tmp_path: Path) -> None:
    with pytest.raises(AudiaGenticError) as exc:
        get_source_catalog(
            tmp_path, "no-such-source", _source(**{"model-discovery": "static-catalog"})
        )
    assert exc.value.code == "CON-SRCCAT-001"


# --- refresh, retry, degradation ------------------------------------------------


def _refresh(tmp_path: Path, responses: list, source_id: str = "src", **source_overrides):
    """Run a refresh with a scripted fetcher; responses items are lists (success)
    or exceptions (raised)."""
    calls = {"count": 0}

    def scripted_fetcher(base_url: str, api_key: str | None):
        index = min(calls["count"], len(responses) - 1)
        calls["count"] += 1
        outcome = responses[index]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    register_catalog_fetcher("scripted", scripted_fetcher, replace=True)
    result = get_source_catalog(
        tmp_path, source_id, _source(connector="scripted", **source_overrides), refresh=True
    )
    return result, calls["count"]


def test_refresh_success_writes_validated_cache(tmp_path: Path) -> None:
    result, calls = _refresh(tmp_path, [[{"model-id": "m1", "context-window": 4096}]])
    assert calls == 1
    assert result.freshness == "fresh"
    assert result.models == [{"model-id": "m1", "context-window": 4096}]
    cached = json.loads(_cache_file(tmp_path, "src").read_text(encoding="utf-8"))
    assert cached["models"] == [{"model-id": "m1", "context-window": 4096}]


def test_transient_failure_retries_once_then_degrades_to_cache(tmp_path: Path) -> None:
    _seed_cache(tmp_path, "src", [{"model-id": "old"}])
    transient = urllib.error.URLError("unreachable")
    result, calls = _refresh(tmp_path, [transient, transient])
    assert calls == 2  # exactly one bounded retry
    assert result.freshness == "cached"
    assert result.stale is True
    assert result.failure_class == "transient"
    assert result.error_code == "CON-SRCCAT-002"
    assert result.models == [{"model-id": "old"}]


def test_transient_failure_then_success_on_retry(tmp_path: Path) -> None:
    transient = urllib.error.URLError("blip")
    result, calls = _refresh(tmp_path, [transient, [{"model-id": "m1"}]])
    assert calls == 2
    assert result.freshness == "fresh"


def test_authorization_failure_never_retries(tmp_path: Path) -> None:
    denied = urllib.error.HTTPError("http://x", 401, "unauthorized", None, None)
    result, calls = _refresh(tmp_path, [denied, [{"model-id": "never"}]])
    assert calls == 1
    assert result.failure_class == "authorization"
    assert result.freshness == "missing"


def test_contract_failure_never_retries(tmp_path: Path) -> None:
    bad = urllib.error.HTTPError("http://x", 404, "not found", None, None)
    result, calls = _refresh(tmp_path, [bad, [{"model-id": "never"}]])
    assert calls == 1
    assert result.failure_class == "contract"


def test_no_cache_degrades_to_missing(tmp_path: Path) -> None:
    result, _ = _refresh(tmp_path, [urllib.error.URLError("x"), urllib.error.URLError("x")])
    assert result.freshness == "missing"
    assert result.failure_class == "transient"


def test_corrupt_cache_is_contract_failure_not_empty(tmp_path: Path) -> None:
    path = _cache_file(tmp_path, "src")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{corrupt", encoding="utf-8")
    with pytest.raises(AudiaGenticError) as exc:
        get_source_catalog(tmp_path, "src", _source(), refresh=False)
    assert exc.value.code == "CON-SRCCAT-001"


def test_unknown_connector_is_configuration_failure(tmp_path: Path) -> None:
    result = get_source_catalog(tmp_path, "src", _source(connector="native-vendor"), refresh=True)
    assert result.failure_class == "configuration"
    assert "no list-api fetcher" in (result.action_needed or "")


def test_secret_resolved_only_into_fetcher_and_never_persisted(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CATALOG_KEY", _SENTINEL_KEY)
    seen: dict = {}

    def fetcher(base_url: str, api_key: str | None):
        seen["key"] = api_key
        return [{"model-id": "m1"}]

    register_catalog_fetcher("keyed", fetcher, replace=True)
    result = get_source_catalog(
        tmp_path,
        "src",
        _source(connector="keyed", **{"api-key-ref": "env:CATALOG_KEY"}),
        refresh=True,
    )
    assert seen["key"] == _SENTINEL_KEY
    assert _SENTINEL_KEY not in json.dumps(result.to_dict())
    assert _SENTINEL_KEY not in _cache_file(tmp_path, "src").read_text(encoding="utf-8")
    timeline = tmp_path / ".audiagentic" / "runtime" / "providers" / "source-catalog-timeline.jsonl"
    if timeline.exists():
        assert _SENTINEL_KEY not in timeline.read_text(encoding="utf-8")


def test_classification_table() -> None:
    assert classify_remote_failure(urllib.error.HTTPError("u", 429, "", None, None)) == "transient"
    assert classify_remote_failure(urllib.error.HTTPError("u", 503, "", None, None)) == "transient"
    assert (
        classify_remote_failure(urllib.error.HTTPError("u", 403, "", None, None)) == "authorization"
    )
    assert classify_remote_failure(TimeoutError()) == "transient"
    assert classify_remote_failure(json.JSONDecodeError("x", "y", 0)) == "contract"
    assert classify_remote_failure(ValueError("bad url")) == "configuration"


# --- filter table (MO12 step 5) --------------------------------------------------


@pytest.mark.parametrize(
    ("model_filter", "expected"),
    [
        (None, ["a/one", "b/two", "c/three-preview"]),
        ({"include": []}, ["a/one", "b/two", "c/three-preview"]),
        ({"include": ["a/*"]}, ["a/one"]),
        ({"exclude": ["*-preview"]}, ["a/one", "b/two"]),
        # overlap: exclude wins over include
        ({"include": ["c/*"], "exclude": ["*-preview"]}, []),
        ({"include": ["a/*", "b/*"], "exclude": ["b/*"]}, ["a/one"]),
    ],
)
def test_filter_table(model_filter, expected) -> None:
    models = [
        {"model-id": "b/two"},
        {"model-id": "c/three-preview"},
        {"model-id": "a/one"},
    ]
    assert [m["model-id"] for m in apply_model_filter(models, model_filter)] == expected


def test_filter_is_stably_sorted() -> None:
    models = [{"model-id": "z"}, {"model-id": "a"}, {"model-id": "m"}]
    assert [m["model-id"] for m in apply_model_filter(models, None)] == ["a", "m", "z"]


def _degraded_timeline_records(tmp_path: Path) -> list[dict]:
    timeline = tmp_path / ".audiagentic" / "runtime" / "providers" / "source-catalog-timeline.jsonl"
    records = [
        json.loads(line) for line in timeline.read_text(encoding="utf-8").splitlines() if line
    ]
    return [r for r in records if r.get("event") == "source-catalog.degraded"]


def test_degraded_missing_timeline_carries_full_contract(tmp_path: Path) -> None:
    """RV390: degraded outcomes persist failure class, error code, action
    needed, and fallback — not just a bare failure-class marker."""
    _refresh(tmp_path, [urllib.error.URLError("x"), urllib.error.URLError("x")])
    records = _degraded_timeline_records(tmp_path)
    assert records, "degraded refresh must record a timeline event"
    attrs = records[-1]["attributes"]
    assert attrs["failure-class"] == "transient"
    assert attrs["error-code"] == "CON-SRCCAT-002"
    assert attrs["action-needed"]
    assert attrs["fallback"] == "none"
    assert attrs["stale"] is False
    assert records[-1]["resource-id"] == "src"


def test_degraded_cached_timeline_carries_staleness(tmp_path: Path) -> None:
    _refresh(tmp_path, [[{"model-id": "m1"}]])  # seed last-known-good cache
    result, _ = _refresh(tmp_path, [urllib.error.URLError("x"), urllib.error.URLError("x")])
    assert result.freshness == "cached"
    attrs = _degraded_timeline_records(tmp_path)[-1]["attributes"]
    assert attrs["fallback"] == "cached"
    assert attrs["stale"] is True
    assert attrs["cached-fetched-at"]
    assert isinstance(attrs["stale-age-seconds"], int)
    assert attrs["stale-age-seconds"] >= 0


def test_degraded_timeline_never_contains_secret(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CATALOG_KEY", _SENTINEL_KEY)
    _refresh(
        tmp_path,
        [urllib.error.URLError("x"), urllib.error.URLError("x")],
        **{"api-key-ref": "env:CATALOG_KEY"},
    )
    timeline = tmp_path / ".audiagentic" / "runtime" / "providers" / "source-catalog-timeline.jsonl"
    assert _SENTINEL_KEY not in timeline.read_text(encoding="utf-8")
