from audiagentic.foundation.invoke.toolchains import npm

from ..descriptors.base import AgentFile, CliInstallRecipe, ProviderDescriptor, ProviderPermissions
from ..descriptors.registry import register

register(ProviderDescriptor(
    provider_id="codex",
    display_name="Codex (OpenAI)",
    cli_probe=["codex", "--version"],
    cli_install=CliInstallRecipe(
        package_manager="npm",
        package_name="@openai/codex",
        executable="codex",
        install=npm.install("@openai/codex"),
        uninstall=npm.uninstall("@openai/codex"),
    ),
    vscode_extensions=(),
    permissions=ProviderPermissions(
        can_write_files=True,
        can_execute_shell=True,
        can_browse_web=False,
        can_read_env=True,
        notes="CLI agent; full-auto mode supported, sandboxed shell execution",
    ),
    agent_files=(
        AgentFile("AGENTS.md", managed=False, description="Codex project instructions"),
    ),
))
