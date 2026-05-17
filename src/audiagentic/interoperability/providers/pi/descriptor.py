from __future__ import annotations

import subprocess

from ..descriptors.base import AgentFile, CliInstallRecipe, ProviderDescriptor, ProviderPermissions
from ..descriptors.registry import register


def _pi_install(project_root=None):
    from audiagentic.provisioning.harness.pi.install import install_to
    from audiagentic.provisioning.home import global_harness_runtime
    try:
        rc = install_to(global_harness_runtime(), project_root=project_root)
    except SystemExit as exc:
        return subprocess.CompletedProcess(["audiagentic", "install"], int(exc.code or 1), "", str(exc))
    except Exception as exc:  # noqa: BLE001
        return subprocess.CompletedProcess(["audiagentic", "install"], 1, "", str(exc))
    return subprocess.CompletedProcess(["audiagentic", "install"], rc, "", "")


def _pi_uninstall(project_root=None):
    from audiagentic.provisioning.harness.pi.install import uninstall_from
    from audiagentic.provisioning.home import global_harness_runtime
    try:
        rc = uninstall_from(global_harness_runtime())
    except Exception as exc:  # noqa: BLE001
        return subprocess.CompletedProcess(["audiagentic", "uninstall"], 1, "", str(exc))
    return subprocess.CompletedProcess(["audiagentic", "uninstall"], rc, "", "")


def _pi_probe(descriptor):
    from audiagentic.provisioning.harness.pi.runner import resolve_agent_bin
    from audiagentic.provisioning.home import global_harness_runtime
    executable = resolve_agent_bin(global_harness_runtime())
    command = [str(executable), "--version"]
    if not executable.exists():
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
    except Exception as exc:  # noqa: BLE001
        return {
            "available": False,
            "command": command,
            "executable": str(executable),
            "returncode": None,
            "stdout": "",
            "stderr": str(exc),
        }
    return {
        "available": completed.returncode == 0,
        "command": command,
        "executable": str(executable),
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


def _install_dispatch(project_root=None):
    import audiagentic.interoperability.providers.pi.descriptor as _m
    return _m._pi_install(project_root)


def _uninstall_dispatch(project_root=None):
    import audiagentic.interoperability.providers.pi.descriptor as _m
    return _m._pi_uninstall(project_root)


def _probe_dispatch(descriptor):
    import audiagentic.interoperability.providers.pi.descriptor as _m
    return _m._pi_probe(descriptor)


register(ProviderDescriptor(
    provider_id="pi",
    display_name="Pi Coding Agent",
    cli_probe=["pi", "--version"],
    cli_install=CliInstallRecipe(
        package_manager="pi-harness",
        package_name="audiagentic-pi-harness",
        executable="pi",
        install_fn=_install_dispatch,
        uninstall_fn=_uninstall_dispatch,
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
