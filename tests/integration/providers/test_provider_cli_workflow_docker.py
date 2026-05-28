from __future__ import annotations

import os

import pytest
from tests.integration.providers.harness import (
    assert_install_result_ok,
    assert_uninstall_result_ok,
    cleanup_provider,
    descriptor_for,
    install_context_for,
    install_provider,
    maybe_skip_provider,
    uninstall_provider,
)

from audiagentic.components.optional.providers.descriptors.registry import (
    all_descriptors,
)
from audiagentic.components.optional.providers.workflow import supports_provider_cli_workflow

pytestmark = [
    pytest.mark.mutates_host,
    pytest.mark.opt_in,
    pytest.mark.long_running,
    pytest.mark.skipif(
        os.environ.get("AUDIAGENTIC_REAL_PROVIDER_CLI_TESTS") != "1",
        reason="real provider CLI install tests are Docker-only and opt-in",
    ),
]

INSTALLABLE_PROVIDER_IDS = sorted(
    provider_id
    for provider_id, descriptor in all_descriptors().items()
    if descriptor.cli_install is not None
)

@pytest.mark.parametrize("provider_id", INSTALLABLE_PROVIDER_IDS)
def test_every_installable_provider_is_workflow_backed(provider_id: str) -> None:
    assert supports_provider_cli_workflow(provider_id), provider_id


@pytest.mark.parametrize("provider_id", INSTALLABLE_PROVIDER_IDS)
@pytest.mark.timeout(1800)
def test_provider_cli_workflow_install_uninstall_roundtrip(provider_id: str, monkeypatch, tmp_path) -> None:
    maybe_skip_provider(provider_id)
    descriptor_for(provider_id)
    project_root = install_context_for(provider_id, monkeypatch, tmp_path)

    install_result = install_provider(provider_id, project_root=project_root)
    assert_install_result_ok(provider_id, install_result)
    assert "workflow-events" in install_result, install_result

    uninstall_result = uninstall_provider(provider_id, project_root=project_root)
    assert_uninstall_result_ok(provider_id, uninstall_result)
    assert "workflow-events" in uninstall_result, uninstall_result
    cleanup_provider(provider_id, project_root=project_root)
