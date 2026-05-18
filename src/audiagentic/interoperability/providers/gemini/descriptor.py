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
    provider_id="gemini",
    display_name="Gemini (Google)",
    description="Google's Gemini CLI. Agentic coding assistant with large context window and Google tool integrations.",
    url="https://github.com/google-gemini/gemini-cli",
    cli_probe=["gemini", "--version"],
    cli_install=CliInstallRecipe(
        package_manager="npm",
        package_name="@google/gemini-cli",
        executable="gemini",
        install=npm.install("@google/gemini-cli"),
        uninstall=npm.uninstall("@google/gemini-cli"),
    ),
    vscode_extensions=(
        VsCodeExtension("Google.gemini-code-assist", "Gemini Code Assist"),
    ),
    permissions=ProviderPermissions(
        can_write_files=True,
        can_execute_shell=True,
        can_browse_web=True,
        can_read_env=True,
        notes="CLI agent with tool use; Google account auth required",
    ),
    agent_files=(
        AgentFile("GEMINI.md", managed=False, description="Gemini project instructions"),
    ),
))
