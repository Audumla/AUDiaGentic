from ...descriptors.base import AgentFile, ProviderDescriptor, ProviderPermissions, cli_recipe
from ...descriptors.registry import register

register(ProviderDescriptor(
    provider_id="plandex",
    display_name="Plandex",
    description="Open-source AI coding agent for large, complex tasks. Manages long-running plans across many files with version control and sandboxed changes.",
    url="https://plandex.ai",
    cli_probe=["plandex", "--version"],
    cli_install=cli_recipe("brew", "plandex-ai/tap/plandex", executable="plandex", uninstall_package="plandex"),
    host_capabilities=(),
    permissions=ProviderPermissions(
        can_write_files=True,
        can_execute_shell=True,
        can_browse_web=False,
        can_read_env=True,
        notes="Plan-and-apply agent; sandboxes changes until user approves; supports OpenAI-compatible backends",
    ),
    agent_files=(
        AgentFile(".plandex/", managed=False, description="Plandex plans and context directory"),
        AgentFile("AGENTS.md", managed=False, description="Shared project instructions"),
    ),
))
