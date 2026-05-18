from __future__ import annotations

import subprocess
from pathlib import Path

from audiagentic.interoperability.providers.descriptors.registry import all_descriptors
from audiagentic.interoperability.providers.lifecycle import (
    install_provider_cli,
    provider_cli_plan,
    provision_all_provider_clis,
    reconcile_all_providers,
    reconcile_provider,
    uninstall_provider_cli,
)


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
    result = install_provider_cli("gemini", dry_run=True)

    assert result["status"] == "planned"
    assert result["command"] == ["npm", "install", "-g", "@google/gemini-cli"]


def test_provider_cli_uninstall_dry_run_does_not_touch_host() -> None:
    result = uninstall_provider_cli("qwen", dry_run=True)

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
    assert providers["copilot"]["package-name"] == "github/gh-copilot"
    assert providers["copilot"]["package-manager"] == "gh-extension"
    assert providers["gemini"]["package-name"] == "@google/gemini-cli"
    assert providers["goose"]["package-manager"] == "brew"
    assert providers["openhands"]["package-manager"] == "uv-tool"
    assert providers["opencode"]["package-name"] == "opencode-ai"
    assert providers["pi"]["package-manager"] == "pi-harness"
    assert providers["qwen"]["package-name"] == "@qwen-code/qwen-code"
    assert providers["local-openai"]["status"] == "skipped"
    assert providers["roo"]["package-manager"] == "vscode"


# --- reconcile tests ---

def test_reconcile_provider_enables_when_cli_available_and_not_enabled(
    monkeypatch, tmp_path: Path
) -> None:
    import audiagentic.interoperability.providers.lifecycle as lifecycle

    monkeypatch.setattr(
        lifecycle,
        "_probe_provider_cli",
        lambda d: {"available": True, "command": ["codex", "--version"],
                   "executable": "/usr/bin/codex", "returncode": 0, "stdout": "1.0", "stderr": ""},
    )

    result = reconcile_provider("codex", project_root=tmp_path)

    assert result["status"] == "enabled"
    assert result["cli-available"] is True
    assert result["was-enabled"] is False
    assert result["action"] == "reconcile"


def test_reconcile_provider_disables_when_cli_absent_and_was_enabled(
    monkeypatch, tmp_path: Path
) -> None:
    import audiagentic.interoperability.providers.lifecycle as lifecycle
    from audiagentic.foundation.config.provider_config import set_provider_enabled

    set_provider_enabled(tmp_path, "codex", enabled=True)
    monkeypatch.setattr(
        lifecycle,
        "_probe_provider_cli",
        lambda d: {"available": False, "command": ["codex", "--version"],
                   "executable": None, "returncode": None, "stdout": "", "stderr": "not found"},
    )

    result = reconcile_provider("codex", project_root=tmp_path)

    assert result["status"] == "disabled"
    assert result["cli-available"] is False
    assert result["was-enabled"] is True


def test_reconcile_provider_noop_when_already_in_sync_enabled(
    monkeypatch, tmp_path: Path
) -> None:
    import audiagentic.interoperability.providers.lifecycle as lifecycle
    from audiagentic.foundation.config.provider_config import set_provider_enabled

    set_provider_enabled(tmp_path, "codex", enabled=True)
    monkeypatch.setattr(
        lifecycle,
        "_probe_provider_cli",
        lambda d: {"available": True, "command": ["codex", "--version"],
                   "executable": "/usr/bin/codex", "returncode": 0, "stdout": "1.0", "stderr": ""},
    )

    result = reconcile_provider("codex", project_root=tmp_path)

    assert result["status"] == "ok"
    assert "surfaces" not in result


def test_reconcile_provider_noop_when_already_in_sync_disabled(
    monkeypatch, tmp_path: Path
) -> None:
    import audiagentic.interoperability.providers.lifecycle as lifecycle

    monkeypatch.setattr(
        lifecycle,
        "_probe_provider_cli",
        lambda d: {"available": False, "command": ["codex", "--version"],
                   "executable": None, "returncode": None, "stdout": "", "stderr": "not found"},
    )

    result = reconcile_provider("codex", project_root=tmp_path)

    assert result["status"] == "ok"
    assert "surfaces" not in result


def test_reconcile_all_providers_returns_one_entry_per_descriptor(
    monkeypatch, tmp_path: Path
) -> None:
    import audiagentic.interoperability.providers.lifecycle as lifecycle

    monkeypatch.setattr(
        lifecycle,
        "_probe_provider_cli",
        lambda d: {"available": False, "command": [], "executable": None,
                   "returncode": None, "stdout": "", "stderr": ""},
    )

    result = reconcile_all_providers(project_root=tmp_path)

    assert result["action"] == "reconcile"
    assert result["ok"] is True
    # vscode-method providers are excluded from auto-reconcile
    from audiagentic.interoperability.providers.descriptors.registry import all_descriptors as _all
    expected = {
        pid for pid, d in _all().items()
        if not (d.cli_install and d.cli_install.package_manager == "vscode")
    }
    provider_ids = {entry["provider-id"] for entry in result["providers"]}
    assert provider_ids == expected
