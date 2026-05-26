from audiagentic.components.optional.providers.adapters.mcp_json import (
    read_mcp_json,
    remove_mcp_json,
    write_mcp_json,
)
from audiagentic.foundation.invoke.toolchains import npm

from ...descriptors.base import (
    CliInstallRecipe,
    McpConfigSpec,
    ProviderDescriptor,
    ProviderPermissions,
    VsCodeExtension,
)
from ...descriptors.registry import register

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
