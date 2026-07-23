"""Pi hooks: bootstrap, cleanup, probe, LSP."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from audiagentic.foundation.config import load_layered_config
from audiagentic.foundation.paths.package import PACKAGE_ROOT

_PI_CONFIG = PACKAGE_ROOT / "config" / "provisioning" / "harness" / "pi.yaml"


def _load_install_config(project_root=None) -> dict:
    return load_layered_config(
        pkg_default_path=_PI_CONFIG,
        project_root=project_root,
        namespace="harness/pi",
    ).get("agent", {})


def _npm() -> str:
    executable = shutil.which("npm")
    if executable is None:
        raise RuntimeError("npm is required for Pi provider lifecycle")
    return executable


def _pi_install(project_root=None):
    try:
        cfg = _load_install_config(project_root)
        packages = cfg.get("packages", {})
        specs = (
            f"{packages.get('cli', '@earendil-works/pi-coding-agent')}@{cfg.get('version', 'latest')}",
            f"{packages.get('mcp_adapter', 'pi-mcp-adapter')}@{cfg.get('mcp_adapter_version', 'latest')}",
            f"{packages.get('acp', 'pi-acp')}@{cfg.get('acp_version', 'latest')}",
        )
        installed = subprocess.run(
            [_npm(), "install", "--global", *specs],
            capture_output=True,
            text=True,
            check=False,
        )
        if installed.returncode != 0:
            return installed
    except Exception as exc:  # noqa: BLE001
        return subprocess.CompletedProcess(["npm", "install"], 1, "", type(exc).__name__)
    return installed


def _pi_uninstall(project_root=None):
    try:
        packages = _load_install_config(project_root).get("packages", {})
        removed = subprocess.run(
            [
                _npm(),
                "uninstall",
                "--global",
                packages.get("cli", "@earendil-works/pi-coding-agent"),
                packages.get("mcp_adapter", "pi-mcp-adapter"),
                packages.get("acp", "pi-acp"),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if removed.returncode != 0:
            return removed
    except Exception as exc:  # noqa: BLE001
        return subprocess.CompletedProcess(["npm", "uninstall"], 1, "", type(exc).__name__)
    return removed


def _pi_lens_present(project_root=None):
    """Report whether the pi-lens extension is installed, without installing it.

    Non-mutating status companion to :func:`_pi_ensure_lens`. ``pi install
    npm:pi-lens`` resolves the package under the harness agent npm prefix, so
    presence of that package directory is the installed signal.
    """
    from audiagentic.components.providers.adapters.pi.system import (
        resolve_system_pi_executable,
        resolve_system_pi_package,
    )
    if resolve_system_pi_executable() is None:
        return {"ok": False, "skipped": "pi harness not installed"}
    if resolve_system_pi_package("pi-lens") is None:
        return {"ok": False, "action_needed": "pi-lens extension is not installed"}
    return {"ok": True}


def _pi_ensure_lens(project_root=None):
    """Install the pi-lens LSP extension into the pi harness (best-effort)."""
    from audiagentic.components.providers.adapters.pi.system import resolve_system_pi_executable
    pi_bin = resolve_system_pi_executable()
    if pi_bin is None:
        return {"ok": False, "skipped": "pi harness not installed"}
    try:
        proc = subprocess.run(
            [pi_bin, "install", "npm:pi-lens"],
            capture_output=True,
            text=True,
            check=False,
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "pi-lens install timed out"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": type(exc).__name__}
    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "error": None if proc.returncode == 0 else "pi-lens install failed",
    }


def _pi_probe(descriptor):
    from audiagentic.components.providers.adapters.pi.system import resolve_system_pi_executable
    resolved = resolve_system_pi_executable()
    command = ["audiagentic", "pi-harness", "metadata"]
    if resolved is None:
        return {
            "available": False,
            "command": command,
            "executable": None,
            "returncode": None,
            "stdout": "",
            "stderr": "command not found",
        }
    executable = resolved

    version = ""
    from audiagentic.components.providers.adapters.pi.system import resolve_system_pi_coding_agent

    pkg = resolve_system_pi_coding_agent()
    package_json = (pkg / "package.json") if pkg is not None else Path("__absent__")
    if package_json.exists():
        try:
            payload = json.loads(package_json.read_text(encoding="utf-8"))
            version = str(payload.get("version") or "")
        except (OSError, json.JSONDecodeError):
            version = ""

    return {
        "available": True,
        "command": command,
        "executable": executable,
        "returncode": 0,
        "stdout": f"pi {version}".strip(),
        "stderr": "",
    }
