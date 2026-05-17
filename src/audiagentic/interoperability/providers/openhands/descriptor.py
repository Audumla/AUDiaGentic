from audiagentic.foundation.invoke.toolchains import uv

from ..descriptors.base import AgentFile, CliInstallRecipe, ProviderDescriptor, ProviderPermissions
from ..descriptors.registry import register

register(ProviderDescriptor(
    provider_id="openhands",
    display_name="OpenHands",
    cli_probe=["openhands", "--version"],
    cli_install=CliInstallRecipe(
        package_manager="uv-tool",
        package_name="openhands",
        executable="openhands",
        install=uv.install("openhands", "--python", "3.12"),
        uninstall=uv.uninstall("openhands"),
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
