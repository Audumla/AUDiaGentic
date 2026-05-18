"""Verify each provider's install/uninstall commands match the official package."""
from __future__ import annotations

import pytest

from audiagentic.interoperability.providers.lifecycle import (
    provider_cli_plan,
)

# (provider_id, action, expected_command)
PROVIDER_COMMANDS = [
    # npm providers
    ("claude",    "install",   ["npm", "install",   "-g", "@anthropic-ai/claude-code"]),
    ("claude",    "uninstall", ["npm", "uninstall",  "-g", "@anthropic-ai/claude-code"]),
    ("cline",     "install",   ["npm", "install",   "-g", "cline"]),
    ("cline",     "uninstall", ["npm", "uninstall",  "-g", "cline"]),
    ("codex",     "install",   ["npm", "install",   "-g", "@openai/codex"]),
    ("codex",     "uninstall", ["npm", "uninstall",  "-g", "@openai/codex"]),
    ("continue",  "install",   ["npm", "install",   "-g", "@continuedev/cli"]),
    ("continue",  "uninstall", ["npm", "uninstall",  "-g", "@continuedev/cli"]),
    ("copilot",   "install",   ["npm", "install",   "-g", "@github/copilot"]),
    ("copilot",   "uninstall", ["npm", "uninstall",  "-g", "@github/copilot"]),
    ("gemini",    "install",   ["npm", "install",   "-g", "@google/gemini-cli"]),
    ("gemini",    "uninstall", ["npm", "uninstall",  "-g", "@google/gemini-cli"]),
    ("opencode",  "install",   ["npm", "install",   "-g", "opencode-ai"]),
    ("opencode",  "uninstall", ["npm", "uninstall",  "-g", "opencode-ai"]),
    ("qwen",      "install",   ["npm", "install",   "-g", "@qwen-code/qwen-code"]),
    ("qwen",      "uninstall", ["npm", "uninstall",  "-g", "@qwen-code/qwen-code"]),
    # uv-tool providers
    ("aider",     "install",   ["uv", "tool", "install", "--force", "--python", "python3.12", "--with", "pip", "aider-chat@latest"]),
    ("aider",     "uninstall", ["uv", "tool", "uninstall", "aider-chat"]),
    ("openhands", "install",   ["uv", "tool", "install", "--python", "3.12", "openhands"]),
    ("openhands", "uninstall", ["uv", "tool", "uninstall", "openhands"]),
    # brew providers
    ("goose",     "install",   ["brew", "install",   "block-goose-cli"]),
    ("goose",     "uninstall", ["brew", "uninstall", "block-goose-cli"]),
]


@pytest.mark.parametrize("provider_id,action,expected", PROVIDER_COMMANDS)
def test_provider_command(provider_id: str, action: str, expected: list[str]) -> None:
    plan = provider_cli_plan(provider_id, action)
    assert plan["status"] == "planned"
    assert plan["command"] == expected, (
        f"{provider_id} {action}: got {plan['command']!r}, expected {expected!r}"
    )


def test_pi_plan_has_no_shell_command() -> None:
    plan = provider_cli_plan("pi", "install")
    assert plan["status"] == "planned"
    assert plan["package-manager"] == "pi-harness"
    assert plan["command"] is None


def test_local_openai_has_no_cli_install() -> None:
    plan = provider_cli_plan("local-openai", "install")
    assert plan["status"] == "skipped"


def test_roo_installs_via_vscode_extension() -> None:
    plan = provider_cli_plan("roo", "install")
    assert plan["status"] == "planned"
    assert plan["package-manager"] == "vscode"
    assert plan["command"] == ["code", "--install-extension", "RooVeterinaryInc.roo-cline", "--force"]


def test_roo_uninstalls_via_vscode_extension() -> None:
    plan = provider_cli_plan("roo", "uninstall")
    assert plan["status"] == "planned"
    assert plan["command"] == ["code", "--uninstall-extension", "RooVeterinaryInc.roo-cline"]
