from audiagentic.foundation.invoke.toolchains import vscode

from ..descriptors.base import (
    AgentFile,
    CliInstallRecipe,
    ProviderDescriptor,
    ProviderPermissions,
    VsCodeExtension,
)
from ..descriptors.registry import register

_EXTENSION_ID = "RooVeterinaryInc.roo-cline"

register(ProviderDescriptor(
    provider_id="roo",
    display_name="Roo Code",
    description="VS Code extension for AI-assisted coding with multi-model support and custom modes.",
    url="https://roocode.com",
    access_mode="env",
    cli_probe=["code", "--list-extensions"],
    cli_install=CliInstallRecipe(
        package_manager="vscode",
        package_name=_EXTENSION_ID,
        executable="code",
        install=vscode.install(_EXTENSION_ID),
        uninstall=vscode.uninstall(_EXTENSION_ID),
    ),
    vscode_extensions=(
        VsCodeExtension(_EXTENSION_ID, "Roo Code"),
    ),
    permissions=ProviderPermissions(
        can_write_files=True,
        can_execute_shell=True,
        can_browse_web=True,
        can_read_env=True,
        notes="VS Code agent with mode support and local model/provider flexibility",
    ),
    agent_files=(
        AgentFile(".roo/rules/audiagentic.md", managed=True, description="AUDiaGentic rules for Roo"),
        AgentFile(".rooignore", managed=False, description="Roo ignore file"),
    ),
))
