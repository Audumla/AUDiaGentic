from ..descriptors.base import AgentFile, ProviderDescriptor, ProviderPermissions, VsCodeExtension
from ..descriptors.registry import register

register(ProviderDescriptor(
    provider_id="roo",
    display_name="Roo Code",
    cli_probe=None,
    vscode_extensions=(
        VsCodeExtension("RooVeterinaryInc.roo-cline", "Roo Code"),
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
