from audiagentic.foundation.invoke.recipes.shell import ShellRecipe

from ...descriptors.base import (
    AgentFile,
    CliInstallRecipe,
    McpConfigSpec,
    ProviderDescriptor,
    ProviderPermissions,
)
from ...descriptors.registry import register
from .mcp_format import read_goose_yaml, remove_goose_yaml, write_goose_yaml

register(ProviderDescriptor(
    provider_id="goose",
    display_name="Goose (Block)",
    description="Open-source AI agent by Block. Extensible toolkit of MCP extensions for dev workflows.",
    url="https://block.github.io/goose",
    cli_probe=["goose", "--version"],
    cli_install=CliInstallRecipe(
        package_manager="script",
        package_name="https://github.com/block/goose/releases/download/stable/download_cli.sh",
        executable="goose",
        install=ShellRecipe((
            "bash",
            "-lc",
            "curl -fsSL https://github.com/block/goose/releases/download/stable/download_cli.sh | CONFIGURE=false bash",
        )),
        uninstall=ShellRecipe((
            "bash",
            "-lc",
            "rm -f \"$HOME/.local/bin/goose\"",
        )),
    ),
    vscode_extensions=(),
    permissions=ProviderPermissions(
        can_write_files=True,
        can_execute_shell=True,
        can_browse_web=True,
        can_read_env=True,
        notes="On-machine agent with MCP/tool orchestration and local/Ollama provider support",
    ),
    agent_files=(
        AgentFile(".goose/config.yaml", managed=False, description="Goose project configuration"),
        AgentFile("AGENTS.md", managed=False, description="Shared project instructions"),
    ),
    mcp_config=McpConfigSpec(
        config_path=".goose/config.yaml",
        reader=read_goose_yaml,
        writer=write_goose_yaml,
        remover=remove_goose_yaml,
        format="goose-yaml",
        refresh_mode="restart-required",
    ),
))
