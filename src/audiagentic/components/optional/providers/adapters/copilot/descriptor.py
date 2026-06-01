from __future__ import annotations

import shutil
import subprocess

from audiagentic.components.optional.providers.adapters.mcp_json import (
    read_mcp_json,
    remove_mcp_json,
    write_mcp_json,
)

from ...descriptors.base import (
    AgentFile,
    McpConfigSpec,
    ProviderDescriptor,
    ProviderPermissions,
    VsCodeExtension,
    cli_recipe,
)
from ...descriptors.registry import register


def _copilot_probe(_descriptor) -> dict:
    command = ["copilot", "--version"]
    executable = shutil.which("copilot")
    if executable is None:
        return {
            "available": False,
            "command": command,
            "executable": None,
            "returncode": None,
            "stdout": "",
            "stderr": "command not found",
        }
    try:
        completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=15)
        if completed.returncode == 0:
            return {
                "available": True,
                "command": command,
                "executable": executable,
                "returncode": completed.returncode,
                "stdout": completed.stdout.strip(),
                "stderr": completed.stderr.strip(),
            }
    except Exception as exc:  # noqa: BLE001
        return {
            "available": True,
            "command": command,
            "executable": executable,
            "returncode": None,
            "stdout": "",
            "stderr": str(exc),
        }
    return {
        "available": True,
        "command": command,
        "executable": executable,
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }

register(ProviderDescriptor(
    provider_id="copilot",
    display_name="GitHub Copilot",
    description="GitHub's AI coding assistant. Inline completions, chat, and multi-file edits across VS Code and JetBrains.",
    url="https://github.com/features/copilot",
    cli_probe=["copilot", "--version"],
    cli_install=cli_recipe("npm", "@github/copilot", executable="copilot", probe_fn=_copilot_probe),
    vscode_extensions=(
        VsCodeExtension("GitHub.copilot", "GitHub Copilot"),
        VsCodeExtension("GitHub.copilot-chat", "GitHub Copilot Chat"),
    ),
    permissions=ProviderPermissions(
        can_write_files=False,
        can_execute_shell=False,
        can_browse_web=False,
        can_read_env=False,
        notes="Completion and chat only; no autonomous tool use in standard mode",
    ),
    instruction_file="COPILOT.md",
    agent_files=(
        AgentFile("COPILOT.md", managed=True, description="Copilot project instructions"),
        AgentFile(".github/copilot-instructions.md", managed=False, description="GitHub Copilot repo instructions"),
    ),
    mcp_config=McpConfigSpec(
        config_path=".mcp.json",
        reader=read_mcp_json,
        writer=write_mcp_json,
        remover=remove_mcp_json,
        format="mcp-json",
        refresh_mode="restart-required",
    ),
))
