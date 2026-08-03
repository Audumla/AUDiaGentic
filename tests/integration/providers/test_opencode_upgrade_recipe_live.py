"""Clean-container proof for the descriptor-managed OpenCode CLI recipe."""
from __future__ import annotations

import os

import pytest


@pytest.mark.integration
@pytest.mark.opt_in
@pytest.mark.mutates_host
@pytest.mark.requires_npm
def test_opencode_install_then_explicit_upgrade_is_verified(tmp_path) -> None:
    if os.environ.get("AUDIAGENTIC_OPENCODE_RECIPE_DOCKER") != "1":
        pytest.skip("set AUDIAGENTIC_OPENCODE_RECIPE_DOCKER=1")

    from audiagentic.components.providers.descriptors.registry import get_descriptor
    from audiagentic.components.providers.services.lifecycle.lifecycle import (
        install_provider_cli,
        probe_provider_cli,
        upgrade_provider_cli,
    )

    installed = install_provider_cli("opencode", project_root=tmp_path, timeout=300)
    assert installed["status"] == "installed", installed

    upgraded = upgrade_provider_cli("opencode", project_root=tmp_path, timeout=300)
    assert upgraded["status"] == "upgraded", upgraded

    descriptor = get_descriptor("opencode")
    assert descriptor is not None
    probe = probe_provider_cli(descriptor)
    assert probe and probe["available"] is True, probe
