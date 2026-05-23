from audiagentic.foundation.invoke.toolchains import npm

from ...descriptors.base import (
    AgentFile,
    CliInstallRecipe,
    McpConfigSpec,
    ProviderDescriptor,
    ProviderPermissions,
    VsCodeExtension,
)
from ...descriptors.registry import register

register(ProviderDescriptor(
    provider_id="continue",
    display_name="Continue",
    description="Open-source AI code assistant for VS Code and JetBrains. Chat, autocomplete, and edit with any model.",
    url="https://continue.dev",
    cli_probe=["cn", "--version"],
    cli_install=CliInstallRecipe(
        package_manager="npm",
        package_name="@continuedev/cli",
        executable="cn",
        install=npm.install("@continuedev/cli"),
        uninstall=npm.uninstall("@continuedev/cli"),
    ),
    vscode_extensions=(
        VsCodeExtension("Continue.continue", "Continue"),
    ),
    permissions=ProviderPermissions(
        can_write_files=True,
        can_execute_shell=False,
        can_browse_web=False,
        can_read_env=False,
        notes="VS Code extension; multi-model backend, primarily completion and chat",
    ),
    agent_files=(
        AgentFile(".continue/config.json", managed=False, description="Continue configuration"),
    ),
    mcp_config=McpConfigSpec(
        config_path=".continue/config.json",
        format="continue-json",
        refresh_mode="restart-required",
    ),
))
