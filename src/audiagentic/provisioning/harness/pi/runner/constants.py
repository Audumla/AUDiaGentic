from __future__ import annotations
from pathlib import Path

DEFAULT_PROVIDER = "audiagentic"
DEFAULT_RIG_PORT = 42001
DEFAULT_SMOKE_TIMEOUT = 60.0
TRUTHY = {"1", "true", "yes", "on"}

_AGENT_DIR = Path(__file__).parent


def _find_package_root(start: Path) -> Path:
    current = start.resolve()
    while current != current.parent:
        if current.name == "audiagentic":
            return current
        current = current.parent
    raise RuntimeError(f"Could not find 'audiagentic' package root from {start}")


_PKG_ROOT = _find_package_root(_AGENT_DIR)
_MODELS_JSON = _PKG_ROOT / "provisioning" / "rig" / "embedded" / "models.json"
_HARNESS_CONFIG = _PKG_ROOT / "config" / "provisioning" / "harness" / "ag.yaml"
