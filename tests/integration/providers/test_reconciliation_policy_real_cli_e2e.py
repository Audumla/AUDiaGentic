"""Real-CLI reconciliation-policy e2e — Docker only, mutates the container.

Two scenarios, both against real installed CLIs (never monkeypatched probes):

1. opencode + pi are already installed (baked into the image at build time,
   see tests/docker/Dockerfile.reconciliation-policy-e2e) — what does a
   default (auto-mode) reconcile actually do with them, and what does an
   allowlist that excludes them do?
2. codex + claude are installed live, during the test itself (real `npm
   install` via the real install_provider_cli path), then reconciled.

Run: docker build -f tests/docker/Dockerfile.reconciliation-policy-e2e \
       -t audiagentic-reconciliation-policy-e2e .
     docker run --rm audiagentic-reconciliation-policy-e2e
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from audiagentic.foundation.components.loader import register_all_components

pytestmark = [
    pytest.mark.mutates_host,
    pytest.mark.slow,
    pytest.mark.skipif(
        os.environ.get("AUDIAGENTIC_DOCKER_TESTS") != "1",
        reason="reconciliation-policy real-CLI e2e runs in Docker",
    ),
    pytest.mark.skipif(
        os.environ.get("AUDIAGENTIC_REAL_PROVIDER_CLI_TESTS") != "1",
        reason="requires real provider CLI install (network + npm)",
    ),
]

register_all_components()


def test_preinstalled_opencode_and_pi_get_auto_enabled(tmp_path: Path) -> None:
    """auto mode (the default, never configured): reconcile enables whatever
    is actually on PATH — this is the exact behavior the bigcherry bug
    report complained about, proven here against real installed CLIs rather
    than a mocked probe."""
    from audiagentic.components.providers.descriptors.registry import get_descriptor
    from audiagentic.components.providers.services.config.provider_config import (
        is_provider_enabled,
    )
    from audiagentic.components.providers.services.lifecycle.lifecycle import probe_provider_cli
    from audiagentic.components.providers.services.reconcile import reconcile_all_providers

    for provider_id in ("opencode", "pi"):
        probe = probe_provider_cli(get_descriptor(provider_id))
        assert probe and probe["available"], (
            f"{provider_id} must be pre-installed in this image "
            f"(Dockerfile.reconciliation-policy-e2e) for this test to be meaningful"
        )

    statuses: dict[str, str] = {}
    reconcile_all_providers(
        project_root=tmp_path, on_provider=lambda pid, status: statuses.__setitem__(pid, status)
    )

    print("reconcile statuses (auto mode, opencode+pi pre-installed):", statuses)
    assert statuses["opencode"] == "enabled"
    assert statuses["pi"] == "enabled"
    assert is_provider_enabled(tmp_path, "opencode") is True
    assert is_provider_enabled(tmp_path, "pi") is True


def test_allowlist_excluding_preinstalled_opencode_and_pi_skips_them(tmp_path: Path) -> None:
    """Same real CLIs on PATH, but an allowlist that excludes them: reconcile
    must leave both disabled — the whole point of the reconciliation-policy
    feature, proven against real installed binaries, not a probe fake."""
    from audiagentic.components.providers.services.config.provider_config import (
        is_provider_enabled,
        set_reconciliation_policy,
    )
    from audiagentic.components.providers.services.reconcile import reconcile_all_providers

    set_reconciliation_policy(tmp_path, mode="allowlist", allowed_providers=["claude"])

    statuses: dict[str, str] = {}
    reconcile_all_providers(
        project_root=tmp_path, on_provider=lambda pid, status: statuses.__setitem__(pid, status)
    )

    print("reconcile statuses (allowlist=['claude'], opencode+pi pre-installed):", statuses)
    assert statuses["opencode"] == "skipped"
    assert statuses["pi"] == "skipped"
    assert is_provider_enabled(tmp_path, "opencode") is False
    assert is_provider_enabled(tmp_path, "pi") is False


def test_installing_codex_and_claude_during_the_test_then_reconciling(tmp_path: Path) -> None:
    """Real npm install of codex + claude, performed by the test itself (not
    baked into the image), via the real install_provider_cli path — then
    reconcile and confirm: (a) install_provider_cli enables immediately,
    independent of reconciliation-policy (it's an explicit user action, not
    auto-detection); (b) a subsequent auto-mode reconcile leaves them
    "ok" (already enabled, in sync), not re-triggering "enabled"."""
    from audiagentic.components.providers.descriptors.registry import get_descriptor
    from audiagentic.components.providers.services.config.provider_config import (
        is_provider_enabled,
    )
    from audiagentic.components.providers.services.lifecycle.lifecycle import (
        install_provider_cli,
        probe_provider_cli,
    )
    from audiagentic.components.providers.services.reconcile import reconcile_all_providers

    for provider_id in ("codex", "claude"):
        result = install_provider_cli(provider_id, project_root=tmp_path, timeout=300)
        print(f"install_provider_cli({provider_id}) ->", result["status"])
        assert result["status"] == "installed", (
            f"real npm install of {provider_id} failed: {result}"
        )
        # install_provider_cli seeds enablement itself — independent of any
        # reconciliation-policy setting (no policy has been configured for
        # this project at all in this test).
        assert is_provider_enabled(tmp_path, provider_id) is True

        probe = probe_provider_cli(get_descriptor(provider_id))
        assert probe and probe["available"], f"{provider_id} should now be on PATH"

    statuses: dict[str, str] = {}
    reconcile_all_providers(
        project_root=tmp_path, on_provider=lambda pid, status: statuses.__setitem__(pid, status)
    )

    print("reconcile statuses after live install (auto mode, default policy):", statuses)
    # Already enabled by install_provider_cli and CLI is present -> already
    # in sync, not re-"enabled".
    assert statuses["codex"] == "ok"
    assert statuses["claude"] == "ok"
