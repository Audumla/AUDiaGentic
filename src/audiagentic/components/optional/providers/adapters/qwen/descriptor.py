from __future__ import annotations

import shutil

from audiagentic.components.optional.providers.adapters.mcp_json import (
    read_mcp_json,
    remove_mcp_json,
    write_mcp_json,
)
from audiagentic.components.optional.providers.adapters.probe import run_cli
from audiagentic.components.optional.providers.adapters.qwen.language_servers import (
    read_language_servers_qwen,
    remove_language_servers_qwen,
    write_language_servers_qwen,
)

from ...descriptors.base import (
    LanguageServersConfigSpec,
    McpConfigSpec,
    ProviderDescriptor,
    ProviderPermissions,
    VsCodeExtension,
    cli_recipe,
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
        completed = run_cli(command)
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
    cli_install=cli_recipe("npm", "@qwen-code/qwen-code", executable="qwen", probe_fn=_qwen_probe),
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
    language_servers_config=LanguageServersConfigSpec(
        config_path=".lsp.json",
        reader=read_language_servers_qwen,
        writer=write_language_servers_qwen,
        remover=remove_language_servers_qwen,
        format="qwen-lsp-json",
    ),
))
