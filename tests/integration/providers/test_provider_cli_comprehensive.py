"""Comprehensive provider CLI install/uninstall verification.

Tests every registered provider descriptor to ensure:
1. All descriptors are correctly registered
2. CliInstallRecipe has valid install/uninstall pairs
3. npm-based providers can install and uninstall
4. Probe correctly detects availability after install/uninstall
5. All toolchain factories produce valid ShellStep instances
"""
from __future__ import annotations

import os
import shutil

import pytest
from tests.integration.providers.harness import (
    assert_health_ok,
    assert_install_result_ok,
    assert_uninstall_result_ok,
    cleanup_provider,
    filtered_provider_ids,
    install_provider,
    non_installable_provider_ids,
    uninstall_provider,
)

from audiagentic.components.providers.descriptors.base import (
    CliInstallRecipe,
    ProviderDescriptor,
)
from audiagentic.components.providers.descriptors.registry import (
    all_descriptors,
    get_descriptor,
)
from audiagentic.foundation.steps import CallableStep, ShellStep
from audiagentic.foundation.toolchains.loader import build_step

pytestmark = [
    pytest.mark.mutates_host,
    pytest.mark.opt_in,
    pytest.mark.skipif(
        os.environ.get("AUDIAGENTIC_REAL_PROVIDER_CLI_TESTS") != "1",
        reason="real provider CLI install tests are opt-in only",
    ),
]

ALL_PROVIDER_IDS = sorted(all_descriptors())
CLI_PROVIDER_IDS = sorted(
    provider_id
    for provider_id, descriptor in all_descriptors().items()
    if descriptor.access_mode == "cli"
)


def _param_ids(values: list[str], reason: str) -> list[pytest.ParameterSet | str]:
    if values:
        return values
    return [pytest.param("__none__", marks=pytest.mark.skip(reason=reason))]

# ---------------------------------------------------------------------------
# Descriptor registry tests
# ---------------------------------------------------------------------------

class TestDescriptorRegistry:
    """Verify all descriptors are registered and well-formed."""

    def test_all_descriptors_count(self) -> None:
        assert len(ALL_PROVIDER_IDS) == len(set(ALL_PROVIDER_IDS))

    def test_expected_provider_ids(self) -> None:
        assert ALL_PROVIDER_IDS
        assert "local-openai" in ALL_PROVIDER_IDS

    def test_no_duplicate_descriptors(self) -> None:
        assert len(ALL_PROVIDER_IDS) == len(set(ALL_PROVIDER_IDS)), "Duplicate provider IDs found"

    @pytest.mark.parametrize("provider_id", ALL_PROVIDER_IDS)
    def test_descriptor_retrievable(self, provider_id: str) -> None:
        desc = get_descriptor(provider_id)
        assert desc is not None, f"Descriptor for {provider_id} not found"
        assert desc.provider_id == provider_id
        assert desc.display_name != ""

    @pytest.mark.parametrize("provider_id", ALL_PROVIDER_IDS)
    def test_descriptor_has_required_fields(self, provider_id: str) -> None:
        desc = get_descriptor(provider_id)
        assert desc.provider_id is not None
        assert desc.display_name is not None
        assert desc.access_mode in ("cli", "env", "none")
        # cli_probe can be None for local-openai (access_mode="none")
        if desc.access_mode == "cli":
            assert desc.cli_probe is not None, f"{provider_id} should have cli_probe"

    @pytest.mark.parametrize("provider_id", CLI_PROVIDER_IDS)
    def test_cli_providers_have_install_recipe(self, provider_id: str) -> None:
        """All cli-access providers should have a CliInstallRecipe."""
        desc = get_descriptor(provider_id)
        assert desc.cli_install is not None, f"{provider_id} should have cli_install"
        assert isinstance(desc.cli_install, CliInstallRecipe)
        assert desc.cli_install.package_manager != ""
        assert desc.cli_install.package_name != ""
        assert desc.cli_install.executable != ""
        assert desc.cli_install.install is not None
        assert desc.cli_install.uninstall is not None

    def test_local_openai_no_install_recipe(self) -> None:
        """local-openai should NOT have a cli_install (access_mode='none')."""
        desc = get_descriptor("local-openai")
        assert desc.cli_install is None
        assert desc.access_mode == "none"
        assert desc.cli_probe is None


# ---------------------------------------------------------------------------
# Toolchain factory tests
# ---------------------------------------------------------------------------

class TestToolchainFactories:
    """Verify build_step produces correct ShellStep commands for each toolchain."""

    def test_npm_install(self) -> None:
        step = build_step("npm", "install", "test-package")
        assert isinstance(step, ShellStep)
        assert step.command == ("npm", "install", "-g", "test-package")

    def test_npm_uninstall(self) -> None:
        step = build_step("npm", "uninstall", "test-package")
        assert isinstance(step, ShellStep)
        assert step.command == ("npm", "uninstall", "-g", "test-package")

    def test_brew_install(self) -> None:
        step = build_step("brew", "install", "test-package")
        assert isinstance(step, ShellStep)
        assert step.command == ("brew", "install", "test-package")

    def test_brew_uninstall(self) -> None:
        step = build_step("brew", "uninstall", "test-package")
        assert isinstance(step, ShellStep)
        assert step.command == ("brew", "uninstall", "test-package")

    def test_uv_install(self) -> None:
        step = build_step("uv", "install", "test-package")
        assert isinstance(step, ShellStep)
        assert step.command == ("uv", "tool", "install", "test-package")

    def test_uv_install_with_extra_flags(self) -> None:
        step = build_step("uv", "install", "test-package", "--python", "3.12")
        assert isinstance(step, ShellStep)
        assert step.command == ("uv", "tool", "install", "test-package", "--python", "3.12")

    def test_uv_uninstall(self) -> None:
        step = build_step("uv", "uninstall", "test-package")
        assert isinstance(step, ShellStep)
        assert step.command == ("uv", "tool", "uninstall", "test-package")

    def test_gh_extension_install(self) -> None:
        step = build_step("gh_extension", "install", "owner/repo")
        assert isinstance(step, ShellStep)
        assert step.command == ("gh", "extension", "install", "owner/repo")

    def test_gh_extension_remove(self) -> None:
        step = build_step("gh_extension", "remove", "owner/repo")
        assert isinstance(step, ShellStep)
        assert step.command == ("gh", "extension", "remove", "owner/repo")

    def test_vscode_install(self) -> None:
        step = build_step("vscode", "install", "publisher.extension")
        assert isinstance(step, ShellStep)
        assert step.command == ("code", "--install-extension", "publisher.extension", "--force")

    def test_vscode_uninstall(self) -> None:
        step = build_step("vscode", "uninstall", "publisher.extension")
        assert isinstance(step, ShellStep)
        assert step.command == ("code", "--uninstall-extension", "publisher.extension")


# ---------------------------------------------------------------------------
# npm provider install/uninstall roundtrip tests
# ---------------------------------------------------------------------------

# Known problematic providers that still need external environment support
_KNOWN_PROBLEMATIC = set()


def _get_npm_providers() -> list[tuple[str, ProviderDescriptor]]:
    """Return (provider_id, descriptor) pairs for npm-based providers."""
    descriptors = all_descriptors()
    return [
        (pid, desc)
        for pid, desc in sorted(descriptors.items())
        if desc.cli_install
        and desc.cli_install.package_manager == "npm"
        and pid not in _KNOWN_PROBLEMATIC
        and pid in filtered_provider_ids(package_manager="npm")
    ]


class TestNpmProviderInstallUninstall:
    """Install/health/uninstall roundtrip for all npm-based providers."""

    @pytest.mark.parametrize("provider_id", _param_ids([pid for pid, _ in _get_npm_providers()], "no npm providers selected"))
    @pytest.mark.timeout(1200)
    def test_install_health_uninstall_roundtrip(self, provider_id: str) -> None:
        desc = get_descriptor(provider_id)
        assert desc.cli_install is not None
        executable = desc.cli_install.executable

        install_result = install_provider(provider_id)
        assert_install_result_ok(provider_id, install_result)

        assert shutil.which(executable) is not None, (
            f"{executable} not found on PATH after install"
        )

        try:
            assert_health_ok(provider_id, install_result)
        finally:
            uninstall_result = uninstall_provider(provider_id)
            assert_uninstall_result_ok(provider_id, uninstall_result)
            assert shutil.which(executable) is None, (
                f"{executable} still found on PATH after uninstall"
            )
            cleanup_provider(provider_id)


# ---------------------------------------------------------------------------
# Provider-specific install recipe validation
# ---------------------------------------------------------------------------

# Providers that need GitHub auth for their brew tap
_KNOWN_BREW_AUTH = {"plandex"}


def _get_brew_providers() -> list[str]:
    """Return provider IDs using brew."""
    return [pid for pid in filtered_provider_ids(package_manager="brew") if pid not in _KNOWN_BREW_AUTH]


def _get_uv_providers() -> list[str]:
    """Return provider IDs using uv-tool."""
    return filtered_provider_ids(package_manager="uv-tool")


class TestBrewProviderInstallUninstall:
    """Install/uninstall + CLI invocation for brew-based providers."""

    @pytest.mark.parametrize("provider_id", _param_ids(_get_brew_providers(), "no brew providers selected"))
    def test_install_uninstall_roundtrip(self, provider_id: str) -> None:
        desc = get_descriptor(provider_id)
        assert desc.cli_install is not None
        executable = desc.cli_install.executable

        install_result = install_provider(provider_id)
        assert_install_result_ok(provider_id, install_result)

        assert shutil.which(executable) is not None, (
            f"{executable} not found on PATH after install"
        )

        assert_health_ok(provider_id, install_result)

        uninstall_result = uninstall_provider(provider_id)
        assert_uninstall_result_ok(provider_id, uninstall_result)

        assert shutil.which(executable) is None, (
            f"{executable} still found on PATH after uninstall"
        )


class TestUvProviderInstallUninstall:
    """Install/uninstall + CLI invocation for uv-tool-based providers."""

    @pytest.mark.parametrize("provider_id", _param_ids(_get_uv_providers(), "no uv-tool providers selected"))
    def test_install_uninstall_roundtrip(self, provider_id: str) -> None:
        if shutil.which("uv") is None:
            pytest.skip("uv not available on PATH in this test environment")
        desc = get_descriptor(provider_id)
        assert desc.cli_install is not None
        executable = desc.cli_install.executable

        install_result = install_provider(provider_id)
        assert_install_result_ok(provider_id, install_result)

        assert shutil.which(executable) is not None, (
            f"{executable} not found on PATH after install"
        )

        assert_health_ok(provider_id, install_result)

        uninstall_result = uninstall_provider(provider_id)
        assert_uninstall_result_ok(provider_id, uninstall_result)

        assert shutil.which(executable) is None, (
            f"{executable} still found on PATH after uninstall"
        )


class TestProviderInstallRecipes:
    """Validate each provider's install/uninstall recipe matches expected package manager."""

    @pytest.mark.parametrize("provider_id", _param_ids(filtered_provider_ids(package_manager="npm"), "no npm providers selected"))
    def test_npm_provider_recipe(self, provider_id: str) -> None:
        desc = get_descriptor(provider_id)
        assert desc.cli_install is not None
        assert desc.cli_install.package_manager == "npm"
        assert isinstance(desc.cli_install.install, ShellStep)
        assert isinstance(desc.cli_install.uninstall, ShellStep)
        assert desc.cli_install.install.command[0] == "npm"
        assert desc.cli_install.uninstall.command[0] == "npm"

    @pytest.mark.parametrize("provider_id", _param_ids(filtered_provider_ids(package_manager="brew"), "no brew providers selected"))
    def test_brew_provider_recipe(self, provider_id: str) -> None:
        desc = get_descriptor(provider_id)
        assert desc.cli_install is not None
        assert desc.cli_install.package_manager == "brew"
        assert isinstance(desc.cli_install.install, ShellStep)
        assert isinstance(desc.cli_install.uninstall, ShellStep)
        assert desc.cli_install.install.command[0] == "brew"
        assert desc.cli_install.uninstall.command[0] == "brew"

    @pytest.mark.parametrize("provider_id", _param_ids(filtered_provider_ids(package_manager="script"), "no script providers selected"))
    def test_script_provider_recipe(self, provider_id: str) -> None:
        desc = get_descriptor(provider_id)
        assert desc.cli_install is not None
        assert desc.cli_install.package_manager == "script"
        assert isinstance(desc.cli_install.install, ShellStep)
        assert isinstance(desc.cli_install.uninstall, ShellStep)
        assert desc.cli_install.install.command[0] == "bash"
        assert desc.cli_install.uninstall.command[0] == "bash"

    @pytest.mark.parametrize("provider_id", _param_ids(filtered_provider_ids(package_manager="uv-tool"), "no uv-tool providers selected"))
    def test_uv_provider_recipe(self, provider_id: str) -> None:
        desc = get_descriptor(provider_id)
        assert desc.cli_install is not None
        assert desc.cli_install.package_manager == "uv-tool"
        assert isinstance(desc.cli_install.install, ShellStep)
        assert isinstance(desc.cli_install.uninstall, ShellStep)
        assert desc.cli_install.install.command[0] == "uv"
        assert desc.cli_install.uninstall.command[0] == "uv"

    @pytest.mark.parametrize("provider_id", _param_ids(filtered_provider_ids(package_manager="gh-extension"), "no gh-extension providers selected"))
    def test_gh_extension_provider_recipe(self, provider_id: str) -> None:
        desc = get_descriptor(provider_id)
        assert desc.cli_install is not None
        assert desc.cli_install.package_manager == "gh-extension"
        assert isinstance(desc.cli_install.install, ShellStep)
        assert isinstance(desc.cli_install.uninstall, ShellStep)
        assert desc.cli_install.install.command[0] == "gh"
        assert desc.cli_install.uninstall.command[0] == "gh"

    @pytest.mark.parametrize("provider_id", _param_ids(filtered_provider_ids(package_manager="vscode"), "no vscode providers selected"))
    def test_vscode_provider_recipe(self, provider_id: str) -> None:
        desc = get_descriptor(provider_id)
        assert desc.cli_install is not None
        assert desc.cli_install.package_manager == "vscode"
        assert isinstance(desc.cli_install.install, ShellStep)
        assert isinstance(desc.cli_install.uninstall, ShellStep)
        assert desc.cli_install.install.command[0] == "code"
        assert desc.cli_install.uninstall.command[0] == "code"

    @pytest.mark.parametrize("provider_id", _param_ids(filtered_provider_ids(package_manager="pi-harness"), "no pi-harness providers selected"))
    def test_pi_provider_recipe(self, provider_id: str) -> None:
        desc = get_descriptor(provider_id)
        assert desc.cli_install is not None
        assert desc.cli_install.package_manager == "pi-harness"
        assert isinstance(desc.cli_install.install, CallableStep)
        assert isinstance(desc.cli_install.uninstall, CallableStep)

    @pytest.mark.parametrize("provider_id", non_installable_provider_ids())
    def test_no_install_provider(self, provider_id: str) -> None:
        desc = get_descriptor(provider_id)
        assert desc.cli_install is None
