"""Unit tests: provider catalog fetching — fetch_provider_catalog, refresh_all_catalogs."""
from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from audiagentic.components.providers.services.catalog.catalog import (
    fetch_provider_catalog,
    refresh_all_catalogs,
)
from audiagentic.foundation.contracts.output import ComponentOutputEvent

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _model(model_id: str) -> dict[str, Any]:
    return {
        "model-id": model_id,
        "display-name": model_id,
        "status": "generally-available",
        "supports-structured-output": False,
        "context-window": 8192,
    }


def _fake_descriptor(provider_id: str, has_catalog: bool = True):
    desc = MagicMock()
    desc.fetch_catalog_fn = (lambda cfg: [_model("test-model-1"), _model("test-model-2")]) if has_catalog else None
    return desc


# ---------------------------------------------------------------------------
# fetch_provider_catalog
# ---------------------------------------------------------------------------

def test_fetch_catalog_unknown_provider_raises(tmp_path: Path) -> None:
    with pytest.raises(Exception, match="no descriptor"):
        fetch_provider_catalog("does-not-exist", project_root=tmp_path)


def test_fetch_catalog_provider_without_fn_raises(tmp_path: Path, monkeypatch) -> None:
    import audiagentic.components.providers.services.catalog.catalog as cat

    monkeypatch.setattr(cat, "all_descriptors", lambda: {"nofetch": _fake_descriptor("nofetch", has_catalog=False)})

    with pytest.raises(Exception, match="not-supported|does not support"):
        fetch_provider_catalog("nofetch", project_root=tmp_path)


def test_fetch_catalog_calls_fn_and_returns_count(tmp_path: Path, monkeypatch) -> None:
    import audiagentic.components.providers.services.catalog.catalog as cat

    monkeypatch.setattr(cat, "all_descriptors", lambda: {"myprovider": _fake_descriptor("myprovider")})
    monkeypatch.setattr(cat, "build_model_catalog", lambda **_: {"models": []})
    monkeypatch.setattr(cat, "write_model_catalog", lambda root, payload: root / "catalog.json")

    result = fetch_provider_catalog("myprovider", project_root=tmp_path)

    assert result["ok"] is True
    assert result["provider_id"] == "myprovider"
    assert result["model_count"] == 2


def test_fetch_catalog_emits_progress(tmp_path: Path, monkeypatch) -> None:
    import audiagentic.components.providers.services.catalog.catalog as cat

    monkeypatch.setattr(cat, "all_descriptors", lambda: {"myprovider": _fake_descriptor("myprovider")})
    monkeypatch.setattr(cat, "build_model_catalog", lambda **_: {"models": []})
    monkeypatch.setattr(cat, "write_model_catalog", lambda root, payload: root / "catalog.json")

    events: list[str] = []
    fetch_provider_catalog("myprovider", project_root=tmp_path, on_progress=lambda e: events.append(e.message))

    assert len(events) >= 2
    assert any("myprovider" in msg for msg in events)
    assert any("model" in msg.lower() for msg in events)


def test_fetch_catalog_timeout_raises(tmp_path: Path, monkeypatch) -> None:
    import time

    import audiagentic.components.providers.services.catalog.catalog as cat

    def _slow_fn(cfg):
        time.sleep(5)
        return []

    slow_desc = MagicMock()
    slow_desc.fetch_catalog_fn = _slow_fn
    monkeypatch.setattr(cat, "all_descriptors", lambda: {"slow": slow_desc})

    with pytest.raises(Exception, match="timeout|timed out"):
        fetch_provider_catalog("slow", project_root=tmp_path, timeout=0.1)


def test_fetch_catalog_empty_result_raises(tmp_path: Path, monkeypatch) -> None:
    import audiagentic.components.providers.services.catalog.catalog as cat

    empty_desc = MagicMock()
    empty_desc.fetch_catalog_fn = lambda cfg: []
    monkeypatch.setattr(cat, "all_descriptors", lambda: {"empty": empty_desc})

    with pytest.raises(Exception, match="empty|no models"):
        fetch_provider_catalog("empty", project_root=tmp_path)


# ---------------------------------------------------------------------------
# refresh_all_catalogs
# ---------------------------------------------------------------------------

def test_refresh_all_catalogs_skips_providers_without_fn(tmp_path: Path, monkeypatch) -> None:
    import audiagentic.components.providers.services.catalog.catalog as cat

    fetched: list[str] = []

    def _mock_fetch(provider_id, *, project_root, **kwargs):
        fetched.append(provider_id)
        return {"provider_id": provider_id, "ok": True, "model_count": 1}

    monkeypatch.setattr(cat, "all_descriptors", lambda: {
        "withcatalog": _fake_descriptor("withcatalog", has_catalog=True),
        "nocatalog": _fake_descriptor("nocatalog", has_catalog=False),
    })
    monkeypatch.setattr(cat, "fetch_provider_catalog", _mock_fetch)

    result = refresh_all_catalogs(project_root=tmp_path)

    assert fetched == ["withcatalog"]
    assert result["ok"] is True
    assert len(result["providers"]) == 1


def test_refresh_all_catalogs_tolerates_single_failure(tmp_path: Path, monkeypatch) -> None:
    import audiagentic.components.providers.services.catalog.catalog as cat

    def _mock_fetch(provider_id, *, project_root, **kwargs):
        if provider_id == "bad":
            raise RuntimeError("network error")
        return {"provider_id": provider_id, "ok": True, "model_count": 2}

    monkeypatch.setattr(cat, "all_descriptors", lambda: {
        "good": _fake_descriptor("good"),
        "bad": _fake_descriptor("bad"),
    })
    monkeypatch.setattr(cat, "fetch_provider_catalog", _mock_fetch)

    result = refresh_all_catalogs(project_root=tmp_path)

    provider_map = {p["provider_id"]: p for p in result["providers"]}
    assert provider_map["good"]["ok"] is True
    assert provider_map["bad"]["ok"] is False
    assert "error" in provider_map["bad"]
    assert result["ok"] is False  # not all succeeded


def test_refresh_all_catalogs_ok_true_when_all_succeed(tmp_path: Path, monkeypatch) -> None:
    import audiagentic.components.providers.services.catalog.catalog as cat

    monkeypatch.setattr(cat, "all_descriptors", lambda: {
        "a": _fake_descriptor("a"),
        "b": _fake_descriptor("b"),
    })
    monkeypatch.setattr(
        cat,
        "fetch_provider_catalog",
        lambda provider_id, *, project_root, **kwargs: {"provider_id": provider_id, "ok": True, "model_count": 1},
    )

    result = refresh_all_catalogs(project_root=tmp_path)

    assert result["ok"] is True
    assert len(result["providers"]) == 2


def test_refresh_all_catalogs_emits_progress_events(tmp_path: Path, monkeypatch) -> None:
    import audiagentic.components.providers.services.catalog.catalog as cat

    monkeypatch.setattr(cat, "all_descriptors", lambda: {
        "a": _fake_descriptor("a"),
        "b": _fake_descriptor("b"),
    })
    monkeypatch.setattr(
        cat,
        "fetch_provider_catalog",
        lambda provider_id, *, project_root, **kwargs: {"provider_id": provider_id, "ok": True, "model_count": 1},
    )

    events: list[ComponentOutputEvent] = []
    refresh_all_catalogs(project_root=tmp_path, on_progress=events.append)

    progress = [e for e in events if e.progress is not None and e.total is not None]
    assert progress, "expected at least one progress event with total"
    assert progress[-1].total == 2.0
    assert any("complete" in e.message.lower() for e in events)
