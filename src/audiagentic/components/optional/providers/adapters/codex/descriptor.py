from audiagentic.components.optional.providers.adapters.codex.language_servers import (
    read_language_servers_codex,
    remove_language_servers_codex,
    write_language_servers_codex,
)
from audiagentic.components.optional.providers.adapters.codex.mcp_format import (
    read_codex_toml,
    remove_codex_toml,
    write_codex_toml,
)

from ...descriptors.base import (
    AgentFile,
    LanguageServersConfigSpec,
    McpConfigSpec,
    ProviderDescriptor,
    ProviderPermissions,
    VsCodeExtension,
    cli_recipe,
)
from ...descriptors.registry import register

register(ProviderDescriptor(
    provider_id="codex",
    prompt_aliases=("cx",),
    display_name="Codex (OpenAI)",
    description="OpenAI's CLI coding agent. Runs tasks autonomously in a sandboxed environment.",
    url="https://github.com/openai/codex",
    cli_probe=["codex", "--version"],
    cli_install=cli_recipe("npm", "@openai/codex", executable="codex"),
    host_capabilities=(
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
        config_path=".codex/config.toml",
        reader=read_codex_toml,
        writer=write_codex_toml,
        remover=remove_codex_toml,
        format="codex-toml",
        refresh_mode="restart-required",
    ),
    language_servers_config=LanguageServersConfigSpec(
        config_path=".codex/config.toml",
        reader=read_language_servers_codex,
        writer=write_language_servers_codex,
        remover=remove_language_servers_codex,
        format="codex-toml",
    ),
))
