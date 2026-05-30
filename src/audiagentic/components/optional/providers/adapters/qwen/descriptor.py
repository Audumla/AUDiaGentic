from __future__ import annotations

import shutil
import subprocess

from audiagentic.components.optional.providers.adapters.mcp_json import (
    read_mcp_json,
    remove_mcp_json,
    write_mcp_json,
)
from audiagentic.foundation.toolchains import npm

from ...descriptors.base import (
    CliInstallRecipe,
    McpConfigSpec,
    ProviderDescriptor,
    ProviderPermissions,
    VsCodeExtension,
)
from ...descriptors.registry import register


def _qwen_probe(_descriptor) -> dict:
    command = ["qwen", "--version"]
    executable = shutil.which("qwen")
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
    provider_id="qwen",
    display_name="Qwen (Alibaba)",
    description="Alibaba Cloud's Qwen Code CLI. Open-source coding agent built on the Qwen model family.",
    url="https://github.com/QwenLM/qwen-code",
    cli_probe=["qwen", "--version"],
    cli_install=CliInstallRecipe(
        package_manager="npm",
        package_name="@qwen-code/qwen-code",
        executable="qwen",
        install=npm.install("@qwen-code/qwen-code"),
        uninstall=npm.uninstall("@qwen-code/qwen-code"),
        probe_fn=_qwen_probe,
    ),
    vscode_extensions=(
        VsCodeExtension("qwenlm.qwen-code-vscode-ide-companion", "Qwen Code Companion"),
    ),
    permissions=ProviderPermissions(
        can_write_files=True,
        can_execute_shell=True,
        can_browse_web=False,
        can_read_env=True,
        notes="CLI agent; Alibaba Cloud account auth required",
    ),
    instruction_file="QWEN.md",
    agent_files=(),
    mcp_config=McpConfigSpec(
        config_path=".mcp.json",
        reader=read_mcp_json,
        writer=write_mcp_json,
        remover=remove_mcp_json,
        format="mcp-json",
        refresh_mode="file-watch",
    ),
))
