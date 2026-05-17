from audiagentic.foundation.invoke.toolchains import brew

from ..descriptors.base import AgentFile, CliInstallRecipe, ProviderDescriptor, ProviderPermissions
from ..descriptors.registry import register

register(ProviderDescriptor(
    provider_id="goose",
    display_name="Goose (Block)",
    cli_probe=["goose", "--version"],
    cli_install=CliInstallRecipe(
        package_manager="brew",
        package_name="block-goose-cli",
        executable="goose",
        install=brew.install("block-goose-cli"),
        uninstall=brew.uninstall("block-goose-cli"),
    ),
    vscode_extensions=(),
    permissions=ProviderPermissions(
        can_write_files=True,
        can_execute_shell=True,
        can_browse_web=True,
        can_read_env=True,
        notes="On-machine agent with MCP/tool orchestration and local/Ollama provider support",
    ),
    agent_files=(
        AgentFile(".goose/config.yaml", managed=False, description="Goose project configuration"),
        AgentFile("AGENTS.md", managed=False, description="Shared project instructions"),
    ),
))
