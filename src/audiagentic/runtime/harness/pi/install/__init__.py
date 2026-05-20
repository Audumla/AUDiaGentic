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


def request_runtime_reload(
    project_root: Path,
    *,
    reason: str,
    component_id: str | None = None,
) -> Path:
    """Request an in-session Pi runtime reload via marker file."""
    path = runtime_reload_request_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "requested_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "reason": reason,
    }
    if component_id:
        payload["component_id"] = component_id
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

    harness_cfg = _c._load_config(project_root=project_root)
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
    harness_cfg = _c._load_config(project_root=project_root)
    materialize_agent_config(target, harness_cfg, project_root=project_root)
    return 0
