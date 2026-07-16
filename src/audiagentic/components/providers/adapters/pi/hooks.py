"""Pi hooks: install, uninstall, probe, LSP."""
from __future__ import annotations

import json
import subprocess


def _pi_install(project_root=None):
    from audiagentic.foundation.paths.home import global_harness_runtime
    from audiagentic.runtime.harness.pi.install import install_to
    try:
        rc = install_to(global_harness_runtime(), project_root=project_root)
    except SystemExit as exc:
        return subprocess.CompletedProcess(["audiagentic", "install"], int(exc.code or 1), "", str(exc))
    except Exception as exc:  # noqa: BLE001
        return subprocess.CompletedProcess(["audiagentic", "install"], 1, "", str(exc))
    return subprocess.CompletedProcess(["audiagentic", "install"], rc, "", "")


def _pi_uninstall(project_root=None):
    from audiagentic.foundation.paths.home import global_harness_runtime
    from audiagentic.runtime.harness.pi.install import uninstall_from
    try:
        rc = uninstall_from(global_harness_runtime())
    except Exception as exc:  # noqa: BLE001
        return subprocess.CompletedProcess(["audiagentic", "uninstall"], 1, "", str(exc))
    return subprocess.CompletedProcess(["audiagentic", "uninstall"], rc, "", "")


def _pi_lens_present(project_root=None):
    """Report whether the pi-lens extension is installed, without installing it.

    Non-mutating status companion to :func:`_pi_ensure_lens`. ``pi install
    npm:pi-lens`` resolves the package under the harness agent npm prefix, so
    presence of that package directory is the installed signal.
    """
    from audiagentic.foundation.paths.home import global_harness_runtime
    from audiagentic.runtime.harness.context import resolve_agent_bin
    runtime = global_harness_runtime()
    if not resolve_agent_bin(runtime).exists():
        return {"ok": False, "skipped": "pi harness not installed"}
    package_dir = runtime / "agent" / "npm" / "node_modules" / "pi-lens"
    if not package_dir.exists():
        return {"ok": False, "action_needed": "pi-lens extension is not installed"}
    return {"ok": True}


def _pi_ensure_lens(project_root=None):
    """Install the pi-lens LSP extension into the pi harness (best-effort)."""
    from audiagentic.foundation.paths.home import global_harness_runtime
    from audiagentic.runtime.harness.context import resolve_agent_bin
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
    from audiagentic.foundation.paths.home import global_harness_runtime
    from audiagentic.runtime.harness.pi.runner import resolve_agent_bin
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
