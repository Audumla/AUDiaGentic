from __future__ import annotations

from unittest.mock import patch

from audiagentic.components.providers.adapters.local_openai.catalog import _fetch_catalog
from audiagentic.components.providers.services.config.provider_catalog import (
    build_model_catalog,
    validate_model_catalog,
)


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        import json

        self._body = json.dumps(payload).encode("utf-8")
        self.status = 200

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def _fetch_with_upstream(models: list[dict]) -> list[dict]:
    with patch(
        "audiagentic.components.providers.adapters.local_openai.catalog.urllib.request.urlopen",
        return_value=_FakeResponse({"data": models}),
    ):
        return _fetch_catalog({})


def test_fetched_catalog_validates_against_schema() -> None:
    models = _fetch_with_upstream(
        [{"id": "local-model-a", "status": "available", "name": "Local Model A"}]
    )
    payload = build_model_catalog(
        provider_id="local-openai",
        models=models,
        fetched_at="2026-07-13T00:00:00Z",
        source="api",
    )
    assert validate_model_catalog(payload) == []


def test_unknown_upstream_status_maps_to_active() -> None:
    models = _fetch_with_upstream([{"id": "m1", "status": "totally-unknown"}])
    assert models[0]["status"] == "active"


def test_missing_status_defaults_to_active() -> None:
    models = _fetch_with_upstream([{"id": "m1"}])
    assert models[0]["status"] == "active"


def test_absent_context_window_uses_positive_fallback() -> None:
    models = _fetch_with_upstream([{"id": "m1"}])
    assert isinstance(models[0]["context-window"], int)
    assert models[0]["context-window"] >= 1


def test_supports_structured_output_stays_boolean() -> None:
    models = _fetch_with_upstream([{"id": "m1", "supports-structured-output": "yes"}])
    assert models[0]["supports-structured-output"] is True
    assert isinstance(models[0]["supports-structured-output"], bool)


def test_deprecated_and_experimental_status_mapping() -> None:
    models = _fetch_with_upstream(
        [
            {"id": "m1", "status": "deprecated"},
            {"id": "m2", "status": "preview"},
        ]
    )
    assert models[0]["status"] == "deprecated"
    assert models[1]["status"] == "experimental"
