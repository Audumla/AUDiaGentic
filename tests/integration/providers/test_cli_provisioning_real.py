from __future__ import annotations

import os
import shutil

import pytest

from audiagentic.interoperability.providers.descriptors.registry import all_descriptors
from audiagentic.interoperability.providers.provisioning import (
    install_provider_cli,
    uninstall_provider_cli,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("AUDIAGENTIC_REAL_PROVIDER_CLI_TESTS") != "1",
    reason="real provider CLI install tests are Docker-only and opt-in",
)


def test_npm_provider_cli_install_uninstall_roundtrip() -> None:
    assert shutil.which("npm") is not None
    failures: list[str] = []

    descriptors = all_descriptors()
    provider_ids = [
        provider_id
        for provider_id, descriptor in sorted(descriptors.items())
        if descriptor.cli_install and descriptor.cli_install.package_manager == "npm"
    ]

    for provider_id in provider_ids:
        install_result = install_provider_cli(provider_id, timeout=600)
        try:
            if install_result["status"] != "installed":
                failures.append(f"{provider_id} install: {install_result}")
                continue
            uninstall_result = uninstall_provider_cli(provider_id, timeout=600)
            if uninstall_result["status"] != "uninstalled":
                failures.append(f"{provider_id} uninstall: {uninstall_result}")
        finally:
            if shutil.which(descriptors[provider_id].cli_install.executable):
                uninstall_provider_cli(provider_id, timeout=600)

    assert failures == []


def test_pi_harness_install_uninstall_roundtrip(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("AUDIAGENTIC_HOME", str(tmp_path / "home"))

    install_result = install_provider_cli("pi", timeout=600, project_root=tmp_path)
    try:
        assert install_result["status"] == "installed"
        assert install_result["probe"]["available"] is True
    finally:
        uninstall_result = uninstall_provider_cli("pi", timeout=600)

    assert uninstall_result["status"] == "uninstalled"
    assert uninstall_result["probe"]["available"] is False
