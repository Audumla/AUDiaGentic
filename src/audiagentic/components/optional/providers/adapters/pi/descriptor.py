from __future__ import annotations

import json
import subprocess

from audiagentic.foundation.invoke.recipes.callable_ import CallableRecipe

from ...descriptors.base import AgentFile, CliInstallRecipe, ProviderDescriptor, ProviderPermissions
from ...descriptors.registry import register


def _pi_install(project_root=None):
    from audiagentic.runtime.harness.pi.install import install_to
    from audiagentic.runtime.home import global_harness_runtime
    try:
        rc = install_to(global_harness_runtime(), project_root=project_root)
    except SystemExit as exc:
        return subprocess.CompletedProcess(["audiagentic", "install"], int(exc.code or 1), "", str(exc))
    except Exception as exc:  # noqa: BLE001
        return subprocess.CompletedProcess(["audiagentic", "install"], 1, "", str(exc))
    return subprocess.CompletedProcess(["audiagentic", "install"], rc, "", "")


def _pi_uninstall(project_root=None):
    from audiagentic.runtime.harness.pi.install import uninstall_from
    from audiagentic.runtime.home import global_harness_runtime
    try:
        rc = uninstall_from(global_harness_runtime())
    except Exception as exc:  # noqa: BLE001
        return subprocess.CompletedProcess(["audiagentic", "uninstall"], 1, "", str(exc))
    return subprocess.CompletedProcess(["audiagentic", "uninstall"], rc, "", "")


def _pi_probe(descriptor):
    from audiagentic.runtime.harness.pi.runner import resolve_agent_bin
    from audiagentic.runtime.home import global_harness_runtime
    harness_runtime = global_harness_runtime()
    executable = resolve_agent_bin(harness_runtime)
    command = ["audiagentic", "pi-harness", "metadata"]
    if not executable.exists():
        return {
            "available": False,
            "command": command,
            "executable": None,
            "returncode": None,
            "stdout": "",
            "stderr": "command not found",
        }

    version = ""
    package_json = harness_runtime / "cli" / "node_modules" / "@earendil-works" / "pi-coding-agent" / "package.json"
    if package_json.exists():
        try:
            payload = json.loads(package_json.read_text(encoding="utf-8"))
            version = str(payload.get("version") or "")
        except (OSError, json.JSONDecodeError):
            version = ""

    return {
        "available": True,
        "command": command,
        "executable": str(executable),
        "returncode": 0,
        "stdout": f"pi {version}".strip(),
        "stderr": "",
    }


def _install_dispatch(project_root=None):
    return _pi_install(project_root)


def _uninstall_dispatch(project_root=None):
    return _pi_uninstall(project_root)


def _probe_dispatch(descriptor):
    return _pi_probe(descriptor)


register(ProviderDescriptor(
    provider_id="pi",
    display_name="Pi Coding Agent",
    description="Lightweight local coding agent TUI by Earendil Works. Managed and launched by the AUDiaGentic harness.",
    url="https://www.earendilworks.com/pi",
    cli_probe=None,
    cli_install=CliInstallRecipe(
        package_manager="pi-harness",
        package_name="audiagentic-pi-harness",
        executable="pi",
        install=CallableRecipe(_install_dispatch, label="pi-harness install"),
        uninstall=CallableRecipe(_uninstall_dispatch, label="pi-harness uninstall"),
        probe_fn=_probe_dispatch,
    ),
    vscode_extensions=(),
    permissions=ProviderPermissions(
        can_write_files=True,
        can_execute_shell=True,
        can_browse_web=False,
        can_read_env=True,
        notes="TUI coding agent; launched and managed by AUDiaGentic harness",
    ),
    agent_files=(
        AgentFile(".pi", managed=False, description="Pi agent runtime directory"),
    ),
))
