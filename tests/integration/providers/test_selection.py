from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
for path in (str(ROOT), str(SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

from audiagentic.contracts.errors import AudiaGenticError
from audiagentic.providers.health import health_check
from audiagentic.providers.selection import select_provider


def _descriptor(provider_id: str, supports_jobs: bool = True) -> dict:
    payload = json.loads(
        (ROOT / "docs" / "examples" / "fixtures" / "provider-descriptor.valid.json").read_text(
            encoding="utf-8"
        )
    )
    payload["provider-id"] = provider_id
    payload["supports-jobs"] = supports_jobs
    return payload


def test_selection_picks_healthy_provider() -> None:
    registry = {"local-openai": _descriptor("local-openai")}
    config = {"local-openai": {"enabled": True, "install-mode": "external-configured"}}
    job = {"provider-id": "local-openai"}
    assert select_provider(job, registry, config) == "local-openai"


def test_selection_rejects_unknown_provider() -> None:
    registry = {"local-openai": _descriptor("local-openai")}
    config = {"local-openai": {"enabled": True, "install-mode": "external-configured"}}
    job = {"provider-id": "unknown"}
    try:
        select_provider(job, registry, config)
    except AudiaGenticError as exc:
        assert exc.kind == "validation"
    else:
        raise AssertionError("expected unknown provider error")


def test_selection_rejects_missing_jobs_capability() -> None:
    registry = {"local-openai": _descriptor("local-openai", supports_jobs=False)}
    config = {"local-openai": {"enabled": True, "install-mode": "external-configured"}}
    job = {"provider-id": "local-openai"}
    try:
        select_provider(job, registry, config)
    except AudiaGenticError as exc:
        assert exc.kind == "validation"
    else:
        raise AssertionError("expected jobs capability error")


def test_selection_rejects_unhealthy_provider() -> None:
    registry = {"local-openai": _descriptor("local-openai")}
    config = {"local-openai": {"enabled": False, "install-mode": "external-configured"}}
    job = {"provider-id": "local-openai"}
    try:
        select_provider(job, registry, config)
    except AudiaGenticError as exc:
        assert exc.kind == "business-rule"
    else:
        raise AssertionError("expected unhealthy provider error")


def test_health_check_matches_fixture_shape() -> None:
    fixture = json.loads(
        (ROOT / "docs" / "examples" / "fixtures" / "provider-health.valid.json").read_text(
            encoding="utf-8"
        )
    )
    result = health_check(
        fixture["provider-id"],
        {"supports-jobs": True},
        {"enabled": True},
        now_fn=lambda: fixture["checked-at"],
    )
    for key in ("contract-version", "provider-id", "status", "configured", "latency-ms", "error", "checked-at"):
        assert key in result
