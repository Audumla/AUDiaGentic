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

register(ProviderDescriptor(
    provider_id="gemini",
    display_name="Gemini (Google)",
    description="Google's Gemini CLI. Agentic coding assistant with large context window and Google tool integrations.",
    url="https://github.com/google-gemini/gemini-cli",
    cli_probe=["gemini", "--version"],
    cli_install=cli_recipe("npm", "@google/gemini-cli", executable="gemini"),
    vscode_extensions=(
        VsCodeExtension("google.gemini-cli-vscode-ide-companion", "Gemini CLI Companion"),
    ),
    permissions=ProviderPermissions(
        can_write_files=True,
        can_execute_shell=True,
        can_browse_web=True,
        can_read_env=True,
        notes="CLI agent with tool use; Google account auth required",
    ),
    instruction_file="GEMINI.md",
    skill_surface_path=".gemini/commands/{tag}.md",
    agent_files=(
        AgentFile("GEMINI.md", managed=False, description="Gemini project instructions"),
    ),
    mcp_config=McpConfigSpec(
        config_path=".gemini/settings.json",
        reader=read_mcp_json,
        writer=write_mcp_json,
        remover=remove_mcp_json,
        format="mcp-json",
        refresh_mode="restart-required",
    ),
))
