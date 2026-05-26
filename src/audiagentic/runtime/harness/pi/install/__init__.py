from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from audiagentic.runtime.harness.reload import (
    build_runtime_sync as _build_sync,
)
from audiagentic.runtime.harness.reload import (
    runtime_reload_request_path,
    write_reload_marker,
)

from . import constants as _c
from .config import materialize_agent_config
from .patches import apply_lockdown_patches

_TARGET = "pi-runtime"


def build_runtime_sync(
    *,
    reason: str,
    component_id: str | None = None,
    target: str = _TARGET,
) -> dict[str, object]:
    return _build_sync(reason=reason, component_id=component_id, target=target)


def request_runtime_reload(
    project_root: Path,
    *,
    reason: str,
    component_id: str | None = None,
) -> Path:
    return write_reload_marker(project_root, reason=reason, component_id=component_id, target=_TARGET)


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
    pi_cfg = _c.load_pi_config(project_root=project_root)
    agent_cfg = pi_cfg.get("agent", {})
    agent_version = _c.AGENT_VERSION or agent_cfg.get("version", "latest")
    mcp_adapter_version = _c.AGENT_MCP_ADAPTER_VERSION or agent_cfg.get("mcp_adapter_version", "latest")

    _c._print(f"Installing AudiaGentic agent {agent_version} into {npm_dir}")
    subprocess.run(
        [npm, "install", "--prefix", str(npm_dir),
         f"@earendil-works/pi-coding-agent@{agent_version}"],
        check=True,
    )

    _c._print(f"Installing MCP adapter into {npm_dir}")
    subprocess.run(
        [npm, "install", "--prefix", str(npm_dir),
         f"pi-mcp-adapter@{mcp_adapter_version}"],
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


def mcp_config_path(project_root: Path | None = None) -> Path:
    from audiagentic.runtime.harness.pi.mcp_format import pi_mcp_path
    return pi_mcp_path()


def read_mcp_config(path: Path) -> dict:
    from audiagentic.runtime.harness.pi.mcp_format import read_pi_mcp_json
    return read_pi_mcp_json(path)


def write_mcp_config(path: Path, entries: dict) -> None:
    from audiagentic.runtime.harness.pi.mcp_format import write_pi_mcp_json
    write_pi_mcp_json(path, entries)


def remove_mcp_config(path: Path, name: str) -> bool:
    from audiagentic.runtime.harness.pi.mcp_format import remove_pi_mcp_json
    return remove_pi_mcp_json(path, name)


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
