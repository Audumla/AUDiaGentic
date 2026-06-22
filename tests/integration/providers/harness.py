from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml

from audiagentic.components.providers.descriptors.base import ProviderDescriptor
from audiagentic.components.providers.descriptors.registry import (
    all_descriptors,
    get_descriptor,
)
from audiagentic.components.providers.services.lifecycle import (
    install_provider_cli,
    uninstall_provider_cli,
)


@dataclass(frozen=True)
class ProviderTestPolicy:
    install_timeout: int = 600
    uninstall_timeout: int = 600
    health_timeout: int = 30
    docker_skip_reason: str | None = None
    use_project_root: bool = False
    require_code_cli: bool = False
    trust_install_probe: bool = True


DEFAULT_POLICY = ProviderTestPolicy()
_POLICY_PATH = Path(__file__).with_name("harness.yaml")


def _load_policy_map() -> dict[str, ProviderTestPolicy]:
    raw = yaml.safe_load(_POLICY_PATH.read_text(encoding="utf-8")) or {}
    providers = raw.get("providers", {})
    if not isinstance(providers, dict):
        raise ValueError(f"provider test harness config missing providers map: {_POLICY_PATH}")
    loaded: dict[str, ProviderTestPolicy] = {}
    for provider_id, payload in providers.items():
        if not isinstance(payload, dict):
            raise ValueError(f"provider test policy must be a mapping: {provider_id}")
        loaded[provider_id] = ProviderTestPolicy(**payload)
    return loaded


PROVIDER_POLICIES = _load_policy_map()


def policy_for(provider_id: str) -> ProviderTestPolicy:
    return PROVIDER_POLICIES.get(provider_id, DEFAULT_POLICY)


def descriptor_for(provider_id: str) -> ProviderDescriptor:
    descriptor = get_descriptor(provider_id)
    assert descriptor is not None
    assert descriptor.cli_install is not None
    return descriptor


def provider_ids(*, package_manager: str | None = None) -> list[str]:
    ids: list[str] = []
    for provider_id, descriptor in sorted(all_descriptors().items()):
        if descriptor.cli_install is None:
            continue
        if package_manager is not None and descriptor.cli_install.package_manager != package_manager:
            continue
        ids.append(provider_id)
    return ids


def non_installable_provider_ids() -> list[str]:
    return sorted(
        provider_id
        for provider_id, descriptor in all_descriptors().items()
        if descriptor.cli_install is None
    )


def workflow_installable_provider_ids() -> list[str]:
    return provider_ids()


def provider_under_test() -> str | None:
    value = os.environ.get("AUDIAGENTIC_PROVIDER_UNDER_TEST")
    return value.strip() if value and value.strip() else None


def filtered_provider_ids(*, package_manager: str | None = None) -> list[str]:
    ids = provider_ids(package_manager=package_manager)
    current = provider_under_test()
    if current is None:
        return ids
    return [provider_id for provider_id in ids if provider_id == current]


def maybe_skip_provider(provider_id: str) -> None:
    policy = policy_for(provider_id)
    current = provider_under_test()
    if current is not None and provider_id != current:
        pytest.skip(f"isolated provider run active for {current}")
    if policy.docker_skip_reason:
        pytest.skip(policy.docker_skip_reason)
    if policy.require_code_cli and shutil.which("code") is None:
        pytest.skip("VS Code CLI is not available in Docker image")


def install_context_for(provider_id: str, monkeypatch, tmp_path: Path) -> Path | None:
    policy = policy_for(provider_id)
    if not policy.use_project_root:
        return None
    monkeypatch.setenv("AUDIAGENTIC_HOME", str(tmp_path / "home"))
    return tmp_path


def install_provider(provider_id: str, *, project_root: Path | None = None) -> dict:
    policy = policy_for(provider_id)
    return install_provider_cli(provider_id, timeout=policy.install_timeout, project_root=project_root)


def uninstall_provider(provider_id: str, *, project_root: Path | None = None) -> dict:
    policy = policy_for(provider_id)
    return uninstall_provider_cli(provider_id, timeout=policy.uninstall_timeout, project_root=project_root)


def cleanup_provider(provider_id: str, *, project_root: Path | None = None) -> None:
    descriptor = descriptor_for(provider_id)
    executable = descriptor.cli_install.executable
    if shutil.which(executable):
        uninstall_provider(provider_id, project_root=project_root)


def choose_health_command(
    executable: str,
    help_flags: list[str],
    cli_probe: list[str] | None = None,
    *,
    timeout: int = 30,
) -> list[str]:
    if cli_probe:
        try:
            result = subprocess.run(
                cli_probe, check=False, capture_output=True, text=True, timeout=timeout,
            )
            if result.returncode == 0:
                return cli_probe
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
            pass

    for flag in help_flags:
        cmd = [executable, flag]
        try:
            result = subprocess.run(
                cmd, check=False, capture_output=True, text=True, timeout=timeout,
            )
            if result.returncode == 0:
                return cmd
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
            continue

    return [executable, "--help"]


def assert_install_result_ok(provider_id: str, result: dict) -> None:
    if result["status"] == "installed":
        return
    descriptor = descriptor_for(provider_id)
    probe = result.get("probe")
    if isinstance(probe, dict) and probe.get("available") is True:
        return
    if shutil.which(descriptor.cli_install.executable) is not None:
        return
    assert result["status"] == "installed", (
        f"{provider_id} install failed: {result.get('reason', result)}"
    )


def assert_uninstall_result_ok(provider_id: str, result: dict) -> None:
    assert result["status"] == "uninstalled", (
        f"{provider_id} uninstall failed: {result.get('reason', result)}"
    )


def assert_health_ok(provider_id: str, install_result: dict) -> None:
    descriptor = descriptor_for(provider_id)
    policy = policy_for(provider_id)
    executable = descriptor.cli_install.executable

    probe = install_result.get("probe")
    if policy.trust_install_probe and isinstance(probe, dict) and probe.get("available") is True:
        return

    command = choose_health_command(
        executable,
        ["--help", "-h", "/?", "--version"],
        descriptor.cli_probe,
        timeout=policy.health_timeout,
    )
    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=policy.health_timeout,
    )
    assert result.returncode == 0, (
        f"{executable} {command[-1]} returned {result.returncode}: "
        f"stdout={result.stdout[:500]} stderr={result.stderr[:500]}"
    )
    output = (result.stdout + result.stderr).strip()
    assert output, f"{executable} health command produced no output"


def real_cli_tests_enabled() -> bool:
    return os.environ.get("AUDIAGENTIC_REAL_PROVIDER_CLI_TESTS") == "1"
