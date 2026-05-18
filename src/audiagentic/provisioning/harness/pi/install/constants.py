from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path


def _print(msg: str) -> None:
    print(msg, flush=True)

# Pinned Pi version. Update here and re-run `audiagentic install` to upgrade.
AGENT_VERSION = "0.75.1"
AGENT_MCP_ADAPTER_VERSION = "latest"

_AGENT_DIR = Path(__file__).parent
_TEMPLATES_DIR = _AGENT_DIR / "templates" / "home" / "agent"


def _find_package_root(start: Path) -> Path:
    """Walk up from *start* until we find a directory named 'audiagentic'.

    This avoids fragile parents[N] counting — works regardless of how deep
    the calling module is nested inside the package.
    """
    current = start.resolve()
    while current != current.parent:
        if current.name == "audiagentic":
            return current
        current = current.parent
    raise RuntimeError(f"Could not find 'audiagentic' package root from {start}")


_PKG_ROOT = _find_package_root(_AGENT_DIR)
_SRC_DIR = _PKG_ROOT.parent  # src/
_REPO_ROOT = _PKG_ROOT.parent.parent  # repo root (dev layout)
_MODELS_JSON = _PKG_ROOT / "provisioning" / "rig" / "embedded" / "models.json"
_HARNESS_CONFIG = _PKG_ROOT / "config" / "provisioning" / "harness" / "ag.yaml"

DEFAULT_PROVIDER = "audiagentic"
DEFAULT_API_KEY = "dummy"
DEFAULT_RIG_PORT = 42001


def _npm() -> str:
    resolved = shutil.which("npm")
    if resolved is None:
        raise SystemExit("npm is required to install the AudiaGentic agent.")
    return resolved


def _load_config(project_root: Path | None = None) -> dict:
    from audiagentic.provisioning.config_loader import load_layered_config
    return load_layered_config(
        pkg_default_path=_HARNESS_CONFIG,
        project_root=project_root,
        namespace="harness/ag",
    )


def _audiagentic_pkg_dir(npm_dir: Path) -> Path:
    return npm_dir / "node_modules" / "@earendil-works" / "pi-coding-agent"
