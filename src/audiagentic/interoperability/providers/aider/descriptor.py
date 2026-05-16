from ..descriptors.base import AgentFile, CliInstallRecipe, ProviderDescriptor, ProviderPermissions
from ..descriptors.registry import register

register(ProviderDescriptor(
    provider_id="aider",
    display_name="Aider",
    cli_probe=["aider", "--version"],
    cli_install=CliInstallRecipe(
        "uv-tool",
        "aider-chat",
        "aider",
        install_command=("uv", "tool", "install", "--force", "--python", "python3.12", "--with", "pip", "aider-chat@latest"),
        uninstall_command=("uv", "tool", "uninstall", "aider-chat"),
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
