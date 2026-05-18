from audiagentic.foundation.invoke.toolchains import uv

from ..descriptors.base import AgentFile, CliInstallRecipe, ProviderDescriptor, ProviderPermissions
from ..descriptors.registry import register

register(ProviderDescriptor(
    provider_id="aider",
    display_name="Aider",
    description="AI pair programming in your terminal. Edit code directly in your git repo via chat.",
    url="https://aider.chat",
    cli_probe=["aider", "--version"],
    cli_install=CliInstallRecipe(
        package_manager="uv-tool",
        package_name="aider-chat",
        executable="aider",
        install=uv.install("aider-chat@latest", "--force", "--python", "python3.12", "--with", "pip"),
        uninstall=uv.uninstall("aider-chat"),
    ),
    vscode_extensions=(),
    permissions=ProviderPermissions(
        can_write_files=True,
        can_execute_shell=True,
        can_browse_web=True,
        can_read_env=True,
        notes="Terminal pair-programming agent; local model capable via OpenAI-compatible backends",
    ),
    agent_files=(
        AgentFile("AGENTS.md", managed=False, description="Shared project instructions"),
        AgentFile(".aider.conf.yml", managed=False, description="Aider project configuration"),
    ),
))
