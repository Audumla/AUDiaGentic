from ..descriptors.base import AgentFile, CliInstallRecipe, ProviderDescriptor, ProviderPermissions
from ..descriptors.registry import register

register(ProviderDescriptor(
    provider_id="openhands",
    display_name="OpenHands",
    cli_probe=["openhands", "--version"],
    cli_install=CliInstallRecipe(
        "uv-tool",
        "openhands",
        "openhands",
        install_command=("uv", "tool", "install", "openhands", "--python", "3.12"),
        uninstall_command=("uv", "tool", "uninstall", "openhands"),
    ),
    vscode_extensions=(),
    permissions=ProviderPermissions(
        can_write_files=True,
        can_execute_shell=True,
        can_browse_web=True,
        can_read_env=True,
        notes="Autonomous development agent; best treated as sandboxed/isolated provider",
    ),
    agent_files=(
        AgentFile(".openhands/settings.json", managed=False, description="OpenHands settings"),
    ),
))
