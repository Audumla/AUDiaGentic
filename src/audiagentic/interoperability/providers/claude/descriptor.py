from ..descriptors.base import (
    AgentFile,
    CliInstallRecipe,
    ProviderDescriptor,
    ProviderPermissions,
    VsCodeExtension,
)
from ..descriptors.registry import register

register(ProviderDescriptor(
    provider_id="claude",
    display_name="Claude (Anthropic)",
    cli_probe=["claude", "--version"],
    cli_install=CliInstallRecipe("npm", "@anthropic-ai/claude-code", "claude"),
    vscode_extensions=(
        VsCodeExtension("anthropics.claude-code", "Claude Code"),
    ),
    permissions=ProviderPermissions(
        can_write_files=True,
        can_execute_shell=True,
        can_browse_web=True,
        can_read_env=True,
        notes="Full project access via tool use; bash, file read/write, web fetch",
    ),
    agent_files=(
        AgentFile("CLAUDE.md", managed=True, description="Project instructions / system prompt"),
        AgentFile(".claude/rules/prompt-tags.md", managed=True, description="Canonical prompt tag rules"),
        AgentFile(".claude/settings.json", managed=False, description="Claude Code user settings"),
    ),
))
