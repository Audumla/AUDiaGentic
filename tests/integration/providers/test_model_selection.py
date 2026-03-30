from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
for path in (str(ROOT), str(SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

from audiagentic.providers.selection import select_provider


def _descriptor(provider_id: str) -> dict:
    return {"contract-version": "v1", "provider-id": provider_id, "install-mode": "external-configured", "supports-jobs": True}


def test_selection_validates_model_catalog_when_present() -> None:
    registry = {"codex": _descriptor("codex")}
    provider_config = {
        "codex": {
            "enabled": True,
            "install-mode": "external-configured",
            "access-mode": "cli",
            "default-model": "gpt-5.4-mini",
            "model-aliases": {"fast": "gpt-5.4-mini"},
        }
    }
    catalogs = {
        "codex": {
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
        }
    }
    job = {"provider-id": "codex", "model-alias": "fast"}
    assert select_provider(job, registry, provider_config, catalogs) == "codex"
