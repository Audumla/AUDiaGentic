from __future__ import annotations

import os
import shutil
from pathlib import Path

from audiagentic.runtime.harness.pi.paths import find_pi_package_root


def _print(msg: str) -> None:
    print(msg, flush=True)

AGENT_VERSION = os.environ.get("AUDIAGENTIC_PI_AGENT_VERSION", "latest")
AGENT_MCP_ADAPTER_VERSION = os.environ.get("AUDIAGENTIC_PI_MCP_ADAPTER_VERSION", "latest")

_AGENT_DIR = Path(__file__).parent
_TEMPLATES_DIR = _AGENT_DIR.parent / "templates" / "home" / "agent"

_PKG_ROOT = find_pi_package_root(_AGENT_DIR)
_SRC_DIR = _PKG_ROOT.parent  # src/
_REPO_ROOT = _PKG_ROOT.parent.parent  # repo root (dev layout)
_RIG_CONFIG = _PKG_ROOT / "config" / "provisioning" / "rig" / "rig.yaml"
_HARNESS_CONFIG = _PKG_ROOT / "config" / "provisioning" / "harness" / "ag.yaml"
_PI_CONFIG = _PKG_ROOT / "config" / "provisioning" / "harness" / "pi.yaml"

DEFAULT_API_KEY = "dummy"


def _npm() -> str:
    resolved = shutil.which("npm")
    if resolved is None:
        raise SystemExit("npm is required to install the AudiaGentic agent.")
    return resolved


def load_harness_config(project_root: Path | None = None) -> dict:
    from audiagentic.runtime.config_loader import load_layered_config
    return load_layered_config(
        pkg_default_path=_HARNESS_CONFIG,
        project_root=project_root,
        namespace="harness/ag",
    )


def load_pi_config(project_root: Path | None = None) -> dict:
    from audiagentic.runtime.config_loader import load_layered_config
    return load_layered_config(
        pkg_default_path=_PI_CONFIG,
        project_root=project_root,
        namespace="harness/pi",
    )


def _audiagentic_pkg_dir(npm_dir: Path) -> Path:
    return npm_dir / "node_modules" / "@earendil-works" / "pi-coding-agent"
