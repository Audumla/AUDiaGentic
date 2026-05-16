from ..descriptors.base import AgentFile, CliInstallRecipe, ProviderDescriptor, ProviderPermissions
from ..descriptors.registry import register

register(ProviderDescriptor(
    provider_id="pi",
    display_name="Pi Coding Agent",
    cli_probe=["pi", "--version"],
    cli_install=CliInstallRecipe("pi-harness", "audiagentic-pi-harness", "pi"),
    vscode_extensions=(),
    permissions=ProviderPermissions(
        can_write_files=True,
        can_execute_shell=True,
        can_browse_web=False,
        can_read_env=True,
        notes="TUI coding agent; launched and managed by AUDiaGentic harness",
    ),
    agent_files=(
        AgentFile(".pi", managed=False, description="Pi agent runtime directory"),
    ),
))
