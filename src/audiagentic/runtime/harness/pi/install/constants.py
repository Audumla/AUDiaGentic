from __future__ import annotations

import os
import shutil
from pathlib import Path

from audiagentic.foundation.contracts.errors import make_error
from audiagentic.runtime.harness.paths import _HARNESS_CONFIG, _PKG_ROOT

# Empty string when env var unset — install_to falls back to pi.yaml agent.version
AGENT_VERSION = os.environ.get("AUDIAGENTIC_PI_AGENT_VERSION", "")
AGENT_MCP_ADAPTER_VERSION = os.environ.get("AUDIAGENTIC_PI_MCP_ADAPTER_VERSION", "")

_AGENT_DIR = Path(__file__).parent
_TEMPLATES_DIR = _AGENT_DIR.parent / "templates" / "home" / "agent"

_SRC_DIR = _PKG_ROOT.parent  # src/
_REPO_ROOT = _PKG_ROOT.parent.parent  # repo root (dev layout)
_PI_CONFIG = _PKG_ROOT / "config" / "provisioning" / "harness" / "pi.yaml"

DEFAULT_API_KEY = "dummy"


def _npm() -> str:
    resolved = shutil.which("npm")
    if resolved is None:
        raise make_error(
            prefix="CFG",
            component="PIINST",
            number=5,
            kind="pi-harness",
            message="npm is required to install the AudiaGentic agent.",
        )
    return resolved


def load_harness_config(project_root: Path | None = None) -> dict:
    from audiagentic.foundation.config import load_layered_config
    return load_layered_config(
        pkg_default_path=_HARNESS_CONFIG,
        project_root=project_root,
        namespace="harness/ag",
    )


def load_pi_config(project_root: Path | None = None) -> dict:
    from audiagentic.foundation.config import load_layered_config
    return load_layered_config(
        pkg_default_path=_PI_CONFIG,
        project_root=project_root,
        namespace="harness/pi",
    )


def _audiagentic_pkg_dir(npm_dir: Path) -> Path:
    return npm_dir / "node_modules" / "@earendil-works" / "pi-coding-agent"
