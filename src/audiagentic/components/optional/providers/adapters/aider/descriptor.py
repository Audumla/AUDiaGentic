from ...descriptors.base import AgentFile, ProviderDescriptor, ProviderPermissions, cli_recipe
from ...descriptors.registry import register

register(ProviderDescriptor(
    provider_id="aider",
    display_name="Aider",
    description="AI pair programming in your terminal. Edit code directly in your git repo via chat.",
    url="https://aider.chat",
    cli_probe=["aider", "--version"],
    cli_install=cli_recipe(
        "uv", "aider-chat@latest", "--force", "--python", "python3.12", "--with", "pip",
        executable="aider", uninstall_package="aider-chat",
    ),
    host_capabilities=(),
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
