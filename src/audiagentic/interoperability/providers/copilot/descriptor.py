from ..descriptors.base import (
    AgentFile,
    CliInstallRecipe,
    ProviderDescriptor,
    ProviderPermissions,
    VsCodeExtension,
)
from ..descriptors.registry import register

register(ProviderDescriptor(
    provider_id="copilot",
    display_name="GitHub Copilot",
    cli_probe=["gh", "copilot", "--help"],
    cli_install=CliInstallRecipe(
        "gh-extension",
        "github/gh-copilot",
        "gh",
        uninstall_name="copilot",
    ),
    vscode_extensions=(
        VsCodeExtension("GitHub.copilot", "GitHub Copilot"),
        VsCodeExtension("GitHub.copilot-chat", "GitHub Copilot Chat"),
    ),
    permissions=ProviderPermissions(
        can_write_files=False,
        can_execute_shell=False,
        can_browse_web=False,
        can_read_env=False,
        notes="Completion and chat only; no autonomous tool use in standard mode",
    ),
    agent_files=(
        AgentFile("COPILOT.md", managed=True, description="Copilot project instructions"),
        AgentFile(".github/copilot-instructions.md", managed=False, description="GitHub Copilot repo instructions"),
    ),
))
