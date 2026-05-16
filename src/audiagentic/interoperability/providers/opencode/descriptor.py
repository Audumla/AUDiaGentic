from ..descriptors.base import AgentFile, CliInstallRecipe, ProviderDescriptor, ProviderPermissions
from ..descriptors.registry import register

register(ProviderDescriptor(
    provider_id="opencode",
    display_name="OpenCode",
    cli_probe=["opencode", "--version"],
    cli_install=CliInstallRecipe("npm", "opencode-ai", "opencode"),
    vscode_extensions=(),
    permissions=ProviderPermissions(
        can_write_files=True,
        can_execute_shell=True,
        can_browse_web=False,
        can_read_env=True,
        notes="CLI agent; multi-provider backend, full tool use",
    ),
    agent_files=(
        AgentFile("AGENTS.md", managed=False, description="OpenCode project instructions"),
    ),
))
