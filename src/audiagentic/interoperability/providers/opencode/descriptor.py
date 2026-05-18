from audiagentic.foundation.invoke.toolchains import npm

from ..descriptors.base import AgentFile, CliInstallRecipe, ProviderDescriptor, ProviderPermissions
from ..descriptors.registry import register

register(ProviderDescriptor(
    provider_id="opencode",
    display_name="OpenCode",
    description="Terminal-based AI coding assistant. Supports multiple LLM providers via a unified CLI.",
    url="https://opencode.ai",
    cli_probe=["opencode", "--version"],
    cli_install=CliInstallRecipe(
        package_manager="npm",
        package_name="opencode-ai",
        executable="opencode",
        install=npm.install("opencode-ai"),
        uninstall=npm.uninstall("opencode-ai"),
    ),
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
