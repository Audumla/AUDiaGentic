import shutil
import subprocess

from audiagentic.foundation.invoke.toolchains import vscode

from ..descriptors.base import (
    AgentFile,
    CliInstallRecipe,
    ProviderDescriptor,
    ProviderPermissions,
    VsCodeExtension,
)
from ..descriptors.registry import register

_EXTENSION_ID = "RooVeterinaryInc.roo-cline"


def _roo_probe(descriptor) -> dict:
    command = ["code", "--list-extensions"]
    if shutil.which("code") is None:
        return {"available": False, "command": command,
                "executable": None, "returncode": None, "stdout": "", "stderr": "code not found"}
    # Use cached extension list if available — avoids spawning VS Code when not needed.
    from ..descriptors.registry import _list_vscode_extensions
    exts = _list_vscode_extensions(allow_probe=False)
    if exts is not None:
        return {"available": _EXTENSION_ID.lower() in exts, "command": command,
                "executable": "code", "returncode": 0, "stdout": "", "stderr": ""}
    # No cache — only probe explicitly (MCP interrogate path).
    try:
        completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=15)
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "command": command, "executable": "code",
                "returncode": None, "stdout": "", "stderr": str(exc)}
    installed = _EXTENSION_ID.lower() in completed.stdout.lower()
    return {
        "available": installed,
        "command": command,
        "executable": "code",
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


register(ProviderDescriptor(
    provider_id="roo",
    display_name="Roo Code",
    description="VS Code extension for AI-assisted coding with multi-model support and custom modes.",
    url="https://roocode.com",
    access_mode="env",
    cli_probe=["code", "--list-extensions"],
    cli_install=CliInstallRecipe(
        package_manager="vscode",
        package_name=_EXTENSION_ID,
        executable="code",
        install=vscode.install(_EXTENSION_ID),
        uninstall=vscode.uninstall(_EXTENSION_ID),
        probe_fn=_roo_probe,
    ),
    vscode_extensions=(
        VsCodeExtension(_EXTENSION_ID, "Roo Code"),
    ),
    permissions=ProviderPermissions(
        can_write_files=True,
        can_execute_shell=True,
        can_browse_web=True,
        can_read_env=True,
        notes="VS Code agent with mode support and local model/provider flexibility",
    ),
    agent_files=(
        AgentFile(".roo/rules/audiagentic.md", managed=True, description="AUDiaGentic rules for Roo"),
        AgentFile(".rooignore", managed=False, description="Roo ignore file"),
    ),
))
