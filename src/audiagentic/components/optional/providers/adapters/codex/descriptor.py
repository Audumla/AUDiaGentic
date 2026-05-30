from audiagentic.components.optional.providers.adapters.mcp_json import (
    read_mcp_json,
    remove_mcp_json,
    write_mcp_json,
)
from audiagentic.foundation.toolchains import npm

from ...descriptors.base import (
    AgentFile,
    CliInstallRecipe,
    McpConfigSpec,
    ProviderDescriptor,
    ProviderPermissions,
    VsCodeExtension,
)
from ...descriptors.registry import register

register(ProviderDescriptor(
    provider_id="codex",
    display_name="Codex (OpenAI)",
    description="OpenAI's CLI coding agent. Runs tasks autonomously in a sandboxed environment.",
    url="https://github.com/openai/codex",
    cli_probe=["codex", "--version"],
    cli_install=CliInstallRecipe(
        package_manager="npm",
        package_name="@openai/codex",
        executable="codex",
        install=npm.install("@openai/codex"),
        uninstall=npm.uninstall("@openai/codex"),
    ),
    vscode_extensions=(
        VsCodeExtension("openai.chatgpt", "ChatGPT / OpenAI"),
    ),
    permissions=ProviderPermissions(
        can_write_files=True,
        can_execute_shell=True,
        can_browse_web=False,
        can_read_env=True,
        notes="CLI agent; full-auto mode supported, sandboxed shell execution",
    ),
    instruction_file="AGENTS.md",
    skill_surface_path=".agents/skills/{tag}/SKILL.md",
    agent_files=(
        AgentFile("AGENTS.md", managed=False, description="Codex project instructions"),
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
