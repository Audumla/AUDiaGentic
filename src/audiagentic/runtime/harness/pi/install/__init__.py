from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path

from audiagentic.cli_io import print_message
from audiagentic.foundation.contracts.errors import AudiaGenticError, make_error
from audiagentic.runtime.harness.reload import (
    build_runtime_sync as _build_sync,
)
from audiagentic.runtime.harness.reload import (
    write_reload_marker,
)

from . import constants as _c
from .config import materialize_agent_config
from .patches import apply_lockdown_patches

logger = logging.getLogger(__name__)
_TARGET = "pi-runtime"


def version_info(project_root: Path | None = None) -> dict[str, str]:
    """Resolve configured agent + MCP adapter versions (env override, else pi.yaml)."""
    pi_cfg = _c.load_pi_config(project_root=project_root)
    agent_cfg = pi_cfg.get("agent", {})
    return {
        "agent": _c.AGENT_VERSION or agent_cfg.get("version", "latest"),
        "mcp_adapter": _c.AGENT_MCP_ADAPTER_VERSION or agent_cfg.get("mcp_adapter_version", "latest"),
    }


def _npm_env() -> dict[str, str]:
    env = os.environ.copy()
    # Node 22 in Docker can intermittently crash compiling large npm installs.
    # JIT-less mode is slower but materially more stable for deterministic tests.
    env.setdefault("NODE_OPTIONS", "--jitless")
    return env


def build_runtime_sync(
    *,
    reason: str,
    component_id: str | None = None,
    target: str = _TARGET,
    has_mcp_servers: bool = True,
) -> dict[str, object]:
    return _build_sync(reason=reason, component_id=component_id, target=target, has_mcp_servers=has_mcp_servers)


def request_runtime_reload(
    project_root: Path,
    *,
    reason: str,
    component_id: str | None = None,
    has_mcp_servers: bool = True,
) -> Path:
    return write_reload_marker(project_root, reason=reason, component_id=component_id, target=_TARGET, has_mcp_servers=has_mcp_servers)


def _validate_agent_install(npm_dir: Path) -> None:
    """Verify that the agent install is complete — detect empty dist/ in nested packages."""
    pi_pkg = npm_dir / "node_modules" / "@earendil-works" / "pi-coding-agent"
    if not pi_pkg.exists():
        raise make_error(
            prefix="RES",
            component="PIINST",
            number=6,
            kind="pi-harness",
            message=f"Agent install failed: {pi_pkg} not found after npm install",
            details={"path": str(pi_pkg)},
        )
    # Walk nested @earendil-works packages and check that each dist/ is non-empty.
    for pkg_dir in (pi_pkg / "node_modules" / "@earendil-works").glob("*"):
        dist = pkg_dir / "dist"
        if dist.exists() and not any(dist.iterdir()):
            raise make_error(
                prefix="RES",
                component="PIINST",
                number=7,
                kind="pi-harness",
                message=(
                f"Agent install incomplete: {pkg_dir.name}/dist is empty.\n"
                f"Run: npm install --prefix {npm_dir} to retry."
                ),
                details={"package": pkg_dir.name, "path": str(dist)},
            )


def install_to(target: Path, project_root: Path | None = None) -> int:
    npm_dir = target / "cli"

    for path in (npm_dir, target / "agent", target / "logs"):
        path.mkdir(parents=True, exist_ok=True)

    rig_bin = target / "rig" / "bin"
    for platform_dir in ("windows", "macOS", "linux"):
        (rig_bin / "llama-server" / platform_dir).mkdir(parents=True, exist_ok=True)
    (rig_bin / "models").mkdir(parents=True, exist_ok=True)
    print_message(f"Rig binary dir: {rig_bin / 'llama-server'}")
    print_message("  Place llama-server binaries in the platform subfolder (windows/macOS/linux).")
    print_message(f"Model dir:      {rig_bin / 'models'}")
    print_message("  Place .gguf model files here.")

    npm = _c._npm()
    pi_cfg = _c.load_pi_config(project_root=project_root)
    agent_cfg = pi_cfg.get("agent", {})
    agent_version = _c.AGENT_VERSION or agent_cfg.get("version", "latest")
    mcp_adapter_version = _c.AGENT_MCP_ADAPTER_VERSION or agent_cfg.get("mcp_adapter_version", "latest")

    # Install both packages in one npm install call so npm resolves the full
    # dependency tree in a single pass. Sequential installs cause npm to
    # reorganize the tree on the second call, which can leave nested package
    # dist/ directories empty (observed with pi-tui on Node 22+).
    print_message(
        f"Installing AudiaGentic agent {agent_version} + MCP adapter {mcp_adapter_version} into {npm_dir}"
    )
    subprocess.run(
        [
            npm, "install", "--prefer-offline", "--prefix", str(npm_dir),
            f"@earendil-works/pi-coding-agent@{agent_version}",
            f"pi-mcp-adapter@{mcp_adapter_version}",
        ],
        check=True,
        env=_npm_env(),
    )
    _validate_agent_install(npm_dir)
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
    return pi_mcp_path(project_root)


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
    from audiagentic.foundation.home import global_harness_runtime
    harness_runtime = global_harness_runtime()
    if not (harness_runtime / "cli" / "node_modules" / ".bin").exists():
        return False
    try:
        refresh_materialized_agent_config(harness_runtime, project_root=project_root)
    except AudiaGenticError:
        logger.warning("Failed to refresh agent config for %s", component_id, exc_info=True, extra={"component": component_id})
    try:
        request_runtime_reload(project_root, reason=reason, component_id=component_id)
    except AudiaGenticError:
        logger.warning("Failed to request runtime reload for %s", component_id, exc_info=True, extra={"component": component_id})
    return True


