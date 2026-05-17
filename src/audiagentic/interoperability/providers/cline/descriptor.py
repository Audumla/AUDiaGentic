from audiagentic.foundation.invoke.toolchains import npm

from ..descriptors.base import (
    AgentFile,
    CliInstallRecipe,
    ProviderDescriptor,
    ProviderPermissions,
    VsCodeExtension,
)
from ..descriptors.registry import register

register(ProviderDescriptor(
    provider_id="cline",
    display_name="Cline",
    cli_probe=["cline", "--version"],
    cli_install=CliInstallRecipe(
        package_manager="npm",
        package_name="cline",
        executable="cline",
        install=npm.install("cline"),
        uninstall=npm.uninstall("cline"),
    ),
    vscode_extensions=(
        VsCodeExtension("saoudrizwan.claude-dev", "Cline"),
    ),
    permissions=ProviderPermissions(
        can_write_files=True,
        can_execute_shell=True,
        can_browse_web=True,
        can_read_env=True,
        notes="VS Code extension with full tool use; operates primarily inside editor",
    ),
    agent_files=(
        AgentFile(".clinerules/prompt-tags.md", managed=True, description="Canonical prompt tag rules for Cline"),
        AgentFile(".clinerules", managed=False, description="Cline rules directory"),
    ),
))
