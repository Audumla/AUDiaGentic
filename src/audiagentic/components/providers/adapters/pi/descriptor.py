from __future__ import annotations

import json
import subprocess

from audiagentic.foundation.mcp.json_format import (
    read_mcp_json,
    remove_mcp_json,
    write_mcp_json,
)
from audiagentic.foundation.workflow.invocation.steps import CallableStep

from ...descriptors.base import (
    AgentFile,
    CliInstallRecipe,
    McpConfigSpec,
    ProviderDescriptor,
    ProviderPermissions,
)
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


def _pi_ensure_lens(project_root=None):
    """Install the pi-lens LSP extension into the pi harness (best-effort).

    pi-lens auto-discovers language servers from PATH, so the language server
    binaries installed by coding-lsp plus this extension are all pi needs — no
    per-language config. Idempotent: re-running `pi install` for an already-present
    extension is safe.

    This is a network npm fetch, so it runs from the explicit LSP dependency
    install (`lsp_install_dependencies`), where slowness is expected and streamed
    — never on the enable event, which must stay responsive. The subprocess is
    bounded by a timeout so it cannot hang indefinitely.
    """
    from audiagentic.runtime.harness.pi.runner.context import resolve_agent_bin
    from audiagentic.runtime.home import global_harness_runtime
    pi_bin = resolve_agent_bin(global_harness_runtime())
    if not pi_bin.exists():
        return {"ok": False, "skipped": "pi harness not installed"}
    try:
        proc = subprocess.run(
            [str(pi_bin), "install", "npm:pi-lens"],
            capture_output=True,
            text=True,
            check=False,
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "pi-lens install timed out"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}
    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "stdout": (proc.stdout or "").strip(),
        "stderr": (proc.stderr or "").strip(),
    }


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
register(ProviderDescriptor(
    provider_id="pi",
    display_name="Pi Coding Agent",
    description="Lightweight local coding agent TUI by Earendil Works. Supports MCP tool use via the pi-mcp-adapter extension.",
    url="https://www.earendilworks.com/pi",
    access_mode="none",
    cli_probe=None,
    cli_install=CliInstallRecipe(
        package_manager="pi-harness",
        package_name="audiagentic-pi-harness",
        executable="pi",
        install=CallableStep(id="install", fn=_pi_install),
        uninstall=CallableStep(id="uninstall", fn=_pi_uninstall),
        probe_fn=_pi_probe,
    ),
    host_capabilities=(),
    permissions=ProviderPermissions(
        can_write_files=True,
        can_execute_shell=True,
        can_browse_web=False,
        can_read_env=True,
        notes="TUI coding agent; MCP tool use available when pi-mcp-adapter is installed",
    ),
    agent_files=(
        AgentFile(".pi", managed=False, description="Pi agent runtime directory"),
    ),
    mcp_config=McpConfigSpec(
        config_path=".mcp.json",
        reader=read_mcp_json,
        writer=write_mcp_json,
        remover=remove_mcp_json,
        format="mcp-json",
        refresh_mode="restart-required",
    ),
    on_lsp_enabled=_pi_ensure_lens,
))
