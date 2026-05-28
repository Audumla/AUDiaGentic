from __future__ import annotations

import shutil
import subprocess

from audiagentic.foundation.invoke.toolchains import uv

from ...descriptors.base import AgentFile, CliInstallRecipe, ProviderDescriptor, ProviderPermissions
from ...descriptors.registry import register


def _openhands_probe(_descriptor) -> dict:
    command = ["openhands", "--version"]
    executable = shutil.which("openhands")
    if executable is None:
        return {
            "available": False,
            "command": command,
            "executable": None,
            "returncode": None,
            "stdout": "",
            "stderr": "command not found",
        }
    try:
        completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=15)
        return {
            "available": completed.returncode == 0,
            "command": command,
            "executable": executable,
            "returncode": completed.returncode,
            "stdout": completed.stdout.strip(),
            "stderr": completed.stderr.strip(),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "available": True,
            "command": command,
            "executable": executable,
            "returncode": None,
            "stdout": "",
            "stderr": str(exc),
        }

register(ProviderDescriptor(
    provider_id="openhands",
    display_name="OpenHands",
    description="Open-source autonomous AI agent (formerly OpenDevin). Runs tasks in sandboxed Docker containers with full shell, browser, and file access.",
    url="https://www.all-hands.dev",
    cli_probe=["openhands", "--version"],
    cli_install=CliInstallRecipe(
        package_manager="uv-tool",
        package_name="openhands",
        executable="openhands",
        install=uv.install("openhands", "--python", "3.12"),
        uninstall=uv.uninstall("openhands"),
        probe_fn=_openhands_probe,
    ),
    vscode_extensions=(),
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
