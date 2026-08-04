"""Real (non-mocked) reconciliation-policy smoke test — Docker only.

Reproduces the exact conditions from the bug report that started the
onboarding-policy plan: a brand-new project, no provider CLIs on PATH, no
TTY. Runs the real reconcile machinery (no monkeypatched probes) inside the
clean `audiagentic-test` image, which deliberately bakes in zero provider
CLIs (see tests/docker/Dockerfile.test's own docstring) — so "not available"
here is a real fact about the container, not a mock.

Run: docker build -f tests/docker/Dockerfile.test -t audiagentic-test .
     docker run --rm audiagentic-test \
       /venv/bin/pytest tests/integration/providers/test_reconciliation_policy_docker_smoke.py -v
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from audiagentic.foundation.components.loader import register_all_components

pytestmark = pytest.mark.skipif(
    os.environ.get("AUDIAGENTIC_DOCKER_TESTS") != "1",
    reason="requires a clean-environment container with no provider CLIs on PATH",
)

register_all_components()


def test_fresh_project_no_clis_defaults_to_auto_and_stays_ok(tmp_path: Path) -> None:
    from audiagentic.components.providers.services.config.provider_config import (
        get_reconciliation_policy,
        is_provider_enabled,
    )
    from audiagentic.components.providers.services.reconcile import (
        reconcile_all_providers,
        resolve_reconciliation_policy,
    )

    # No TTY, no MCP ctx in this environment — ask() must time out immediately,
    # never hang, and resolve_reconciliation_policy must persist the safe default.
    resolve_reconciliation_policy(tmp_path)
    assert get_reconciliation_policy(tmp_path) == {"mode": "auto"}

    statuses: dict[str, str] = {}

    def _on_provider(provider_id: str, status: str) -> None:
        statuses[provider_id] = status

    result = reconcile_all_providers(project_root=tmp_path, on_provider=_on_provider)

    assert result["ok"] is True
    # Nothing installed in this image -> nothing to enable; every eligible
    # provider is a real "ok" (already-disabled, in sync), never "enabled"
    # or "skipped" (skipped only applies when a CLI IS detected).
    assert statuses, "expected at least one eligible provider to be reconciled"
    assert set(statuses.values()) == {"ok"}
    assert all(is_provider_enabled(tmp_path, pid) is False for pid in statuses)
