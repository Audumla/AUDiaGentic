from __future__ import annotations

import subprocess

from audiagentic.interoperability.providers.descriptors.registry import all_descriptors
from audiagentic.interoperability.providers.lifecycle import (
    install_provider_cli,
    provider_cli_plan,
    provision_all_provider_clis,
    uninstall_provider_cli,
)


def _ok(command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(command, 0, stdout="ok\n", stderr="")


def test_provider_cli_plan_uses_descriptor_recipe() -> None:
    plan = provider_cli_plan("codex", "install")

    assert plan["status"] == "planned"
    assert plan["command"] == ["npm", "install", "-g", "@openai/codex"]
    assert plan["executable"] == "codex"


def test_registry_includes_local_llm_harness_providers() -> None:
    providers = all_descriptors()

    assert {"aider", "goose", "openhands", "roo"}.issubset(providers)


def test_provider_cli_uninstall_uses_descriptor_recipe() -> None:
    plan = provider_cli_plan("opencode", "uninstall")

    assert plan["status"] == "planned"
    assert plan["command"] == ["npm", "uninstall", "-g", "opencode-ai"]


def test_pi_provider_cli_plan_uses_harness_recipe() -> None:
    plan = provider_cli_plan("pi", "install")

    assert plan["status"] == "planned"
    assert plan["package-manager"] == "pi-harness"
    # Pi uses install_fn (callable hook), so command is None in the plan
    assert plan["command"] is None
    assert plan["executable"] == "pi"


def test_provider_cli_install_dry_run_does_not_touch_host() -> None:
    result = install_provider_cli("gemini", dry_run=True, runner=_ok)

    assert result["status"] == "planned"
    assert result["command"] == ["npm", "install", "-g", "@google/gemini-cli"]


def test_provider_cli_uninstall_dry_run_does_not_touch_host() -> None:
    result = uninstall_provider_cli("qwen", dry_run=True, runner=_ok)

    assert result["status"] == "planned"
    assert result["command"] == ["npm", "uninstall", "-g", "@qwen-code/qwen-code"]


def test_pi_provider_cli_install_uses_harness_installer(monkeypatch) -> None:
    import audiagentic.interoperability.providers.lifecycle as lifecycle
    import audiagentic.interoperability.providers.pi.descriptor as pi_descriptor

    monkeypatch.setattr(pi_descriptor, "_pi_install",
        lambda project_root=None: subprocess.CompletedProcess(["audiagentic", "install"], 0, "", ""))
    monkeypatch.setattr(lifecycle, "_probe_provider_cli",
        lambda descriptor: {"available": True, "command": ["pi", "--version"],
                            "executable": "/tmp/pi", "returncode": 0, "stdout": "0.74.0", "stderr": ""})

    result = install_provider_cli("pi")

    assert result["status"] == "installed"
    assert result["package-manager"] == "pi-harness"


def test_pi_provider_cli_uninstall_uses_harness_uninstaller(monkeypatch) -> None:
    import audiagentic.interoperability.providers.lifecycle as lifecycle
    import audiagentic.interoperability.providers.pi.descriptor as pi_descriptor

    monkeypatch.setattr(pi_descriptor, "_pi_uninstall",
        lambda project_root=None: subprocess.CompletedProcess(["audiagentic", "uninstall"], 0, "", ""))
    monkeypatch.setattr(lifecycle, "_probe_provider_cli",
        lambda descriptor: {"available": False, "command": ["pi", "--version"],
                            "executable": None, "returncode": None, "stdout": "", "stderr": "command not found"})

    result = uninstall_provider_cli("pi")

    assert result["status"] == "uninstalled"
    assert result["package-manager"] == "pi-harness"


def test_all_provider_cli_dry_run_covers_installable_providers() -> None:
    result = provision_all_provider_clis("install", dry_run=True)
    providers = {entry["provider-id"]: entry for entry in result["providers"]}

    assert result["ok"] is True
    assert providers["aider"]["package-manager"] == "uv-tool"
    assert providers["codex"]["package-name"] == "@openai/codex"
    assert providers["claude"]["package-name"] == "@anthropic-ai/claude-code"
    assert providers["cline"]["package-name"] == "cline"
    assert providers["continue"]["package-name"] == "@continuedev/cli"
    assert providers["copilot"]["package-manager"] == "gh-extension"
    assert providers["gemini"]["package-name"] == "@google/gemini-cli"
    assert providers["goose"]["package-manager"] == "brew"
    assert providers["openhands"]["package-manager"] == "uv-tool"
    assert providers["opencode"]["package-name"] == "opencode-ai"
    assert providers["pi"]["package-manager"] == "pi-harness"
    assert providers["qwen"]["package-name"] == "@qwen-code/qwen-code"
    assert providers["local-openai"]["status"] == "skipped"
    assert providers["roo"]["status"] == "skipped"
