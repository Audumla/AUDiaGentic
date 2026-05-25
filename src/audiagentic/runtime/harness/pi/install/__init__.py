from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from . import constants as _c
from .config import materialize_agent_config
from .patches import apply_lockdown_patches


def runtime_reload_request_path(project_root: Path) -> Path:
    return project_root / ".audiagentic" / "runtime" / "harness" / "reload-request.json"


def _runtime_action_for_reason(reason: str) -> str:
    if reason in {
        "component-installed",
        "component-uninstalled",
        "component-enabled",
        "component-disabled",
        "manual-refresh",
        "mcp-refresh-tool",
    }:
        return "reload_required"
    if reason in {"session-ui-visibility-updated"}:
        return "reload_required"
    return "refresh_required"


def build_runtime_sync(
    *,
    reason: str,
    component_id: str | None = None,
    target: str = "pi-runtime",
) -> dict[str, object]:
    payload: dict[str, object] = {
        "target": target,
        "action": _runtime_action_for_reason(reason),
        "reason": reason,
    }
    if component_id:
        payload["component_id"] = component_id
    return payload


def request_runtime_reload(
    project_root: Path,
    *,
    reason: str,
    component_id: str | None = None,
) -> Path:
    """Write a structured runtime action marker for the active Pi session."""
    path = runtime_reload_request_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "requested_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        **build_runtime_sync(reason=reason, component_id=component_id),
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def install_to(target: Path, project_root: Path | None = None) -> int:
    npm_dir = target / "cli"

    for path in (npm_dir, target / "agent", target / "logs"):
        path.mkdir(parents=True, exist_ok=True)

    rig_bin = target / "rig" / "bin"
    for platform_dir in ("windows", "macOS", "linux"):
        (rig_bin / "llama-server" / platform_dir).mkdir(parents=True, exist_ok=True)
    (rig_bin / "models").mkdir(parents=True, exist_ok=True)
    _c._print(f"Rig binary dir: {rig_bin / 'llama-server'}")
    _c._print("  Place llama-server binaries in the platform subfolder (windows/macOS/linux).")
    _c._print(f"Model dir:      {rig_bin / 'models'}")
    _c._print("  Place .gguf model files here.")

    npm = _c._npm()

    _c._print(f"Installing AudiaGentic agent {_c.AGENT_VERSION} into {npm_dir}")
    subprocess.run(
        [npm, "install", "--prefix", str(npm_dir),
         f"@earendil-works/pi-coding-agent@{_c.AGENT_VERSION}"],
        check=True,
    )

    _c._print(f"Installing MCP adapter into {npm_dir}")
    subprocess.run(
        [npm, "install", "--prefix", str(npm_dir),
         f"pi-mcp-adapter@{_c.AGENT_MCP_ADAPTER_VERSION}"],
        check=True,
    )
    apply_lockdown_patches(npm_dir, project_root=project_root)

    harness_cfg = _c.load_harness_config(project_root=project_root)
    materialize_agent_config(target, harness_cfg, project_root=project_root)
    return 0


def uninstall_from(target: Path) -> int:
    """Remove the Pi harness CLI and generated agent config.

    Rig binaries, models, and logs are left in place because they may be large
    user-managed assets or useful diagnostics.
    """
    for path in (target / "cli", target / "agent"):
        if path.exists():
            shutil.rmtree(path)
    return 0


def refresh_materialized_agent_config(target: Path, project_root: Path | None = None) -> int:
    """Rebuild generated agent config for current project/component state."""
    harness_cfg = _c.load_harness_config(project_root=project_root)
    materialize_agent_config(target, harness_cfg, project_root=project_root)
    return 0


def refresh_harness_config_if_installed(
    project_root: Path,
    *,
    reason: str,
    component_id: str | None = None,
) -> bool:
    """Regenerate mcp.json and request runtime reload if harness is installed.

    Returns True if harness was present and config was refreshed.
    """
    from audiagentic.runtime.home import global_harness_runtime
    harness_runtime = global_harness_runtime()
    if not (harness_runtime / "cli" / "node_modules" / ".bin").exists():
        return False
    try:
        refresh_materialized_agent_config(harness_runtime, project_root=project_root)
    except Exception:
        pass
    try:
        request_runtime_reload(project_root, reason=reason, component_id=component_id)
    except Exception:
        pass
    return True
