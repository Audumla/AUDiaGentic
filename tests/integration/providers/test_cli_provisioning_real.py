from __future__ import annotations

import os

import pytest
from tests.integration.providers.harness import (
    assert_install_result_ok,
    assert_uninstall_result_ok,
    cleanup_provider,
    install_context_for,
    install_provider,
    provider_ids,
    uninstall_provider,
)

pytestmark = [
    pytest.mark.mutates_host,
    pytest.mark.opt_in,
    pytest.mark.skipif(
        os.environ.get("AUDIAGENTIC_REAL_PROVIDER_CLI_TESTS") != "1",
        reason="real provider CLI install tests are Docker-only and opt-in",
    ),
]


@pytest.mark.timeout(1200)
def test_npm_provider_cli_install_uninstall_roundtrip() -> None:
    failures: list[str] = []
    known_problematic = set()

    for provider_id in provider_ids(package_manager="npm"):
        if provider_id in known_problematic:
            continue
        install_result = install_provider(provider_id)
        try:
            if install_result["status"] != "installed":
                failures.append(f"{provider_id} install: {install_result}")
                continue
            uninstall_result = uninstall_provider(provider_id)
            if uninstall_result["status"] != "uninstalled":
                failures.append(f"{provider_id} uninstall: {uninstall_result}")
        finally:
            cleanup_provider(provider_id)

    assert failures == []


@pytest.mark.timeout(1200)
def test_pi_harness_install_uninstall_roundtrip(monkeypatch, tmp_path) -> None:
    project_root = install_context_for("pi", monkeypatch, tmp_path)
    install_result = install_provider("pi", project_root=project_root)
    try:
        assert_install_result_ok("pi", install_result)
        assert install_result["probe"]["available"] is True
    finally:
        uninstall_result = uninstall_provider("pi", project_root=project_root)

    assert_uninstall_result_ok("pi", uninstall_result)
    assert uninstall_result["probe"]["available"] is False
