from __future__ import annotations

from ...descriptors.base import AgentFile, ProviderDescriptor, ProviderPermissions, cli_recipe
from ...descriptors.registry import register
from ..probe import probe_cli_version


def _openhands_probe(_descriptor) -> dict:
    return probe_cli_version("openhands", ["openhands", "--version"])

register(ProviderDescriptor(
    provider_id="openhands",
    display_name="OpenHands",
    description="Open-source autonomous AI agent (formerly OpenDevin). Runs tasks in sandboxed Docker containers with full shell, browser, and file access.",
    url="https://www.all-hands.dev",
    cli_probe=["openhands", "--version"],
    cli_install=cli_recipe("uv", "openhands", "--python", "3.12", executable="openhands", probe_fn=_openhands_probe),
    host_capabilities=(),
    permissions=ProviderPermissions(
        can_write_files=True,
        can_execute_shell=True,
        can_browse_web=True,
        can_read_env=True,
        notes="Autonomous development agent; best treated as sandboxed/isolated provider",
    ),
    agent_files=(
        AgentFile(".openhands/settings.json", managed=False, description="OpenHands settings"),
    ),
))
