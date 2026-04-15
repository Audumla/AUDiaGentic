from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
for path in (str(ROOT), str(SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

from audiagentic.foundation.config.provider_catalog import (
    build_model_catalog,
    validate_model_catalog,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.interoperability.providers.models import resolve_model_selection


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
        assert exc.kind == "validation"
    else:
        raise AssertionError("expected validation error")
